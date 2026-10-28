//! Python3.12 syntax admission and exact callable extent selection.
use ruff_python_ast::{
    self as py, Stmt,
    token::TokenKind,
    visitor::{self, Visitor},
};
use ruff_python_parser::{Mode, ParseErrorType, ParseOptions, parse_unchecked};
use ruff_text_size::Ranged;
pub struct PythonFile {
    pub source: String,
    module: py::ModModule,
    headers: Vec<usize>,
}
impl PythonFile {
    pub fn parse(source: String) -> Option<Self> {
        if source.contains('\0')
            || source.starts_with('\u{feff}')
            || !super::admission::lexical_limits(&source)
        {
            return None;
        }
        let parsed = parse_unchecked(
            &source,
            ParseOptions::from(Mode::Module).with_target_version(py::PythonVersion::PY312),
        );
        // CPython ast.parse retains repeated keywords; only compilation rejects them.
        if parsed
            .errors()
            .iter()
            .any(|e| !matches!(e.error, ParseErrorType::DuplicateKeywordArgumentError(_)))
            || !parsed.unsupported_syntax_errors().is_empty()
        {
            return None;
        }
        for token in parsed.tokens().iter() {
            if token.kind() == TokenKind::Name
                && !ken_text::unicode::identifier(
                    &source[token.range().start().to_usize()..token.range().end().to_usize()],
                )
            {
                return None;
            }
        }
        // Ruff ranges include decorators; CPython lineno starts at async/def/class.
        let headers = parsed
            .tokens()
            .iter()
            .filter(|t| {
                matches!(
                    t.kind(),
                    TokenKind::Def | TokenKind::Class | TokenKind::Async
                )
            })
            .map(|t| t.range().start().to_usize())
            .collect();
        let py::Mod::Module(module) = parsed.into_syntax() else {
            return None;
        };
        if !super::admission::syntax(&module, &source) {
            return None;
        }
        Some(Self {
            source,
            module,
            headers,
        })
    }
    pub fn body(&self, name: &str, extent: [usize; 2]) -> Option<&[Stmt]> {
        let mut finder = Find {
            source: &self.source,
            headers: &self.headers,
            name,
            extent,
            found: Vec::new(),
        };
        finder.visit_body(&self.module.body);
        if finder.found.len() == 1 {
            Some(finder.found[0])
        } else {
            None
        }
    }
}
struct Find<'s, 'a> {
    source: &'s str,
    headers: &'s [usize],
    name: &'s str,
    extent: [usize; 2],
    found: Vec<&'a [Stmt]>,
}
impl<'a> Visitor<'a> for Find<'_, 'a> {
    fn visit_stmt(&mut self, node: &'a Stmt) {
        let selected = match node {
            Stmt::FunctionDef(n) => Some((
                n.name.as_str(),
                n.body.as_slice(),
                n.decorator_list
                    .last()
                    .map(|d| d.range().end().to_usize())
                    .unwrap_or(node.range().start().to_usize()),
                n.name.range().start().to_usize(),
            )),
            Stmt::ClassDef(n) => Some((
                n.name.as_str(),
                n.body.as_slice(),
                n.decorator_list
                    .last()
                    .map(|d| d.range().end().to_usize())
                    .unwrap_or(node.range().start().to_usize()),
                n.name.range().start().to_usize(),
            )),
            _ => None,
        };
        if let Some((name, body, after, before)) = selected {
            let header = self
                .headers
                .iter()
                .find(|start| **start >= after && **start <= before)
                .copied()
                .unwrap_or(before);
            let start = 1 + self.source[..header]
                .bytes()
                .filter(|b| *b == b'\n')
                .count();
            let end = 1 + self.source[..node.range().end().to_usize().saturating_sub(1)]
                .bytes()
                .filter(|b| *b == b'\n')
                .count();
            if name == self.name && end == self.extent[1] && self.extent[0] <= start && start <= end
            {
                self.found.push(body);
            }
        }
        visitor::walk_stmt(self, node);
    }
}
