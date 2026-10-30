//! One confined physical read supplies current documentation and later quotes.
use crate::{Candidate, IndexedCandidate, Preview, Result, Snippet, Symbol, invalid, reasoners};
use blake2::{
    Blake2bVar,
    digest::{Update, VariableOutput},
};
use ken_core::{
    project::{DiscoveryContext, ProjectPaths},
    source_reader::SourceFileReader,
};
use ken_retrieval::python_operation_witnesses::PythonFile;
use ken_syntax::{GrammarCatalog, ParserRegistry};
use ken_text::PythonText;
use ruff_python_ast::{
    self as py, Expr, Stmt,
    visitor::{self, Visitor},
};
use ruff_text_size::Ranged;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
    sync::Arc,
};
pub trait CurrentSources {
    /// One request owns one immutable source cache. Providers may be reused by a host.
    fn begin_request(&mut self) -> Result<()> {
        Ok(())
    }
    fn resolve(&mut self, row: &IndexedCandidate) -> Result<Symbol>;
    fn preview(&mut self, candidate: &Candidate) -> Result<Preview>;
}
struct Snapshot {
    hash: Vec<u8>,
    symbols: Vec<Symbol>,
    lines: std::result::Result<Vec<String>, String>,
}
pub struct NativeSources {
    reader: SourceFileReader,
    catalog: Arc<GrammarCatalog>,
    cache: BTreeMap<String, Snapshot>,
}
impl NativeSources {
    pub fn new(root: &Path, catalog: Arc<GrammarCatalog>) -> Result<Self> {
        let context = DiscoveryContext::from_process()?;
        let paths = ProjectPaths::at(root, &context)?;
        Ok(Self {
            reader: SourceFileReader::new(&paths)?,
            catalog,
            cache: BTreeMap::new(),
        })
    }
    fn read(&self, path: &str) -> Result<Snapshot> {
        let bytes = self
            .reader
            .open(Path::new(path))?
            .read_bounded(2 * 1024 * 1024)?
            .ok_or_else(|| invalid("source exceeds 2 MiB"))?;
        let sha = format!("{:x}", Sha256::digest(&bytes));
        let mut blake = Blake2bVar::new(32).expect("fixed digest");
        blake.update(&bytes);
        let mut hash = vec![0; 32];
        blake.finalize_variable(&mut hash).expect("fixed digest");
        let python = Path::new(path)
            .extension()
            .is_some_and(|e| e == "py" || e == "pyi");
        let (symbols, lines) = if python {
            let decoded =
                ken_text::source::decode_python(&bytes).map_err(|e| invalid(e.to_string()))?;
            let normalized = decoded.replace("\r\n", "\n").replace('\r', "\n");
            let file = PythonFile::parse(normalized)
                .ok_or_else(|| invalid("invalid Python source syntax"))?;
            let symbols = python_symbols(&file, path, &sha)?;
            (
                symbols,
                Ok(ken_text::unicode::splitlines(&decoded)
                    .into_iter()
                    .map(str::to_owned)
                    .collect()),
            )
        } else {
            let registry = ParserRegistry::with_shared_catalog(self.catalog.clone());
            let language = registry
                .detect(Path::new(path), Some(&bytes))
                .map_err(|e| invalid(e.to_string()))?
                .ok_or_else(|| invalid("unsupported source language"))?;
            let parsed = registry
                .parse(language, &bytes, path)
                .map_err(|e| invalid(e.to_string()))?;
            let mut symbols = parsed
                .symbols
                .into_iter()
                .map(|s| Symbol {
                    path: path.into(),
                    qualname: s.qualname,
                    kind: s.kind,
                    line: s.line_start,
                    end_line: s.line_end,
                    documentation: s.docstring.unwrap_or_default().into(),
                    sha256: sha.clone(),
                    calls: vec![],
                    refreshed: false,
                    doc_scope: "parser_excerpt".into(),
                    implementation_line: 0,
                })
                .collect::<Vec<_>>();
            if let Some(doc) = parsed.docstring.filter(|d| !d.is_empty()) {
                symbols.push(Symbol {
                    path: path.into(),
                    qualname: path.into(),
                    kind: "module".into(),
                    line: 1,
                    end_line: byte_lines(&bytes).min(150),
                    documentation: doc.into(),
                    sha256: sha.clone(),
                    calls: vec![],
                    refreshed: false,
                    doc_scope: "parser_excerpt".into(),
                    implementation_line: 0,
                });
            }
            let lines = std::str::from_utf8(&bytes)
                .map(|s| {
                    ken_text::unicode::splitlines(s)
                        .into_iter()
                        .map(str::to_owned)
                        .collect()
                })
                .map_err(|e| e.to_string());
            (symbols, lines)
        };
        Ok(Snapshot {
            hash,
            symbols,
            lines,
        })
    }
}
impl CurrentSources for NativeSources {
    fn begin_request(&mut self) -> Result<()> {
        self.cache.clear();
        Ok(())
    }
    fn resolve(&mut self, row: &IndexedCandidate) -> Result<Symbol> {
        if !self.cache.contains_key(&row.path) {
            if self.cache.len() >= 24 {
                return Err(invalid("source file budget exhausted"));
            }
            let snapshot = self.read(&row.path)?;
            self.cache.insert(row.path.clone(), snapshot);
        }
        let snapshot = &self.cache[&row.path];
        let mut symbol = snapshot
            .symbols
            .iter()
            .find(|s| s.kind == row.kind && s.qualname == row.qualname)
            .cloned()
            .ok_or_else(|| invalid("indexed symbol no longer present or parser unavailable"))?;
        symbol.refreshed = snapshot.hash != row.content_hash;
        Ok(symbol)
    }
    fn preview(&mut self, candidate: &Candidate) -> Result<Preview> {
        let snapshot = self
            .cache
            .get(&candidate.path)
            .ok_or_else(|| invalid("assessed source snapshot unavailable"))?;
        let symbol = snapshot
            .symbols
            .iter()
            .find(|s| s.kind == candidate.kind && s.qualname == candidate.symbol)
            .ok_or_else(|| invalid("assessed owner unavailable"))?;
        if candidate.source.sha256 != symbol.sha256 {
            return Err(invalid("preview does not match assessed source"));
        }
        preview(
            symbol,
            &snapshot.symbols,
            snapshot.lines.as_ref().map_err(invalid)?,
            &candidate.matched_formulation,
        )
    }
}
fn byte_lines(bytes: &[u8]) -> usize {
    let mut lines = 0;
    let mut at = 0;
    let mut start = 0;
    while at < bytes.len() {
        if bytes[at] == b'\r' || bytes[at] == b'\n' {
            lines += 1;
            if bytes[at] == b'\r' && bytes.get(at + 1) == Some(&b'\n') {
                at += 1;
            }
            start = at + 1;
        }
        at += 1;
    }
    lines + usize::from(start < bytes.len())
}
fn line(file: &PythonFile, offset: usize) -> usize {
    1 + file.source[..offset.min(file.source.len())]
        .bytes()
        .filter(|b| *b == b'\n')
        .count()
}
fn end_line(file: &PythonFile, node: &impl Ranged) -> usize {
    line(file, node.range().end().to_usize().saturating_sub(1))
}
fn literal(file: &PythonFile, body: &[Stmt]) -> Option<PythonText> {
    let Stmt::Expr(statement) = body.first()? else {
        return None;
    };
    let Expr::StringLiteral(string) = statement.value.as_ref() else {
        return None;
    };
    let mut points = Vec::new();
    for part in string.value.iter() {
        let raw = &file.source[part.range.start().to_usize()..part.range.end().to_usize()];
        points.extend_from_slice(ken_syntax::decode_python_string_literal(raw)?.codepoints());
    }
    Some(clean_doc(PythonText::from_codepoints(points)?))
}
fn clean_doc(value: PythonText) -> PythonText {
    // inspect.cleandoc expands tabs, removes common indentation after the first
    // line, and strips only empty leading/trailing lines after dedenting.
    let mut expanded = Vec::new();
    let mut column = 0;
    for &p in value.codepoints() {
        if p == 9 {
            let n = 8 - column % 8;
            expanded.extend(std::iter::repeat_n(32, n));
            column += n;
        } else {
            expanded.push(p);
            if matches!(p, 10 | 13) {
                column = 0;
            } else {
                column += 1;
            }
        }
    }
    let mut lines = expanded
        .split(|p| *p == 10)
        .map(|p| p.to_vec())
        .collect::<Vec<_>>();
    let indent = |line: &Vec<u32>| {
        line.iter()
            .take_while(|p| char::from_u32(**p).is_some_and(ken_text::unicode::whitespace))
            .count()
    };
    let margin = lines
        .iter()
        .skip(1)
        .filter(|p| indent(p) < p.len())
        .map(indent)
        .min();
    if let Some(first) = lines.first_mut() {
        first.drain(..indent(first));
    }
    if let Some(margin) = margin {
        for line in lines.iter_mut().skip(1) {
            line.drain(..margin.min(line.len()));
        }
    }
    while lines.last().is_some_and(Vec::is_empty) {
        lines.pop();
    }
    while lines.first().is_some_and(Vec::is_empty) {
        lines.remove(0);
    }
    let mut out = Vec::new();
    for (index, line) in lines.into_iter().enumerate() {
        if index > 0 {
            out.push(10);
        }
        out.extend(line);
    }
    PythonText::from_codepoints(out).expect("existing code points")
}
fn body_start(file: &PythonFile, body: &[Stmt]) -> usize {
    let body = if matches!(body.first(),Some(Stmt::Expr(e))if matches!(e.value.as_ref(),Expr::StringLiteral(_)))
    {
        &body[1..]
    } else {
        body
    };
    body.first().map_or(0, |n| file.declaration_line(n))
}
fn python_symbols(file: &PythonFile, path: &str, sha: &str) -> Result<Vec<Symbol>> {
    let body = &file.module().body;
    let mut symbols = Vec::new();
    if let Some(doc) = literal(file, body).filter(|d| !d.is_empty()) {
        let node = &body[0];
        symbols.push(Symbol {
            path: path.into(),
            qualname: path.into(),
            kind: "module".into(),
            line: file.declaration_line(node),
            end_line: end_line(file, node),
            documentation: doc,
            sha256: sha.into(),
            calls: vec![],
            refreshed: false,
            doc_scope: "full".into(),
            implementation_line: body_start(file, body),
        });
    }
    walk(file, body, "", path, sha, &mut symbols);
    Ok(symbols)
}
fn walk(
    file: &PythonFile,
    body: &[Stmt],
    prefix: &str,
    path: &str,
    sha: &str,
    symbols: &mut Vec<Symbol>,
) {
    for node in body {
        let definition = match node {
            Stmt::FunctionDef(n) => Some((n.name.as_str(), n.body.as_slice(), false)),
            Stmt::ClassDef(n) => Some((n.name.as_str(), n.body.as_slice(), true)),
            _ => None,
        };
        if let Some((name, body, class)) = definition {
            let qualname = format!("{prefix}{name}");
            let symbol = Symbol {
                path: path.into(),
                qualname: qualname.clone(),
                kind: if class {
                    "class"
                } else if prefix.is_empty() {
                    "function"
                } else {
                    "method"
                }
                .into(),
                line: file.declaration_line(node),
                end_line: end_line(file, node),
                documentation: literal(file, body).unwrap_or_else(|| "".into()),
                sha256: sha.into(),
                calls: if class { vec![] } else { calls(file, body) },
                refreshed: false,
                doc_scope: "full".into(),
                implementation_line: body_start(file, body),
            };
            if let Some(existing) = symbols
                .iter_mut()
                .find(|s| s.kind == symbol.kind && s.qualname == symbol.qualname)
            {
                *existing = symbol;
            } else {
                symbols.push(symbol);
            }
            if class {
                walk(file, body, &format!("{qualname}."), path, sha, symbols);
            }
        } else {
            let body = match node {
                Stmt::If(n) => Some(n.body.as_slice()),
                Stmt::For(n) => Some(n.body.as_slice()),
                Stmt::While(n) => Some(n.body.as_slice()),
                Stmt::With(n) => Some(n.body.as_slice()),
                Stmt::Try(n) => Some(n.body.as_slice()),
                _ => None,
            };
            if let Some(body) = body {
                walk(file, body, prefix, path, sha, symbols);
            }
        }
    }
}
#[derive(Clone, Copy)]
enum Node<'a> {
    Stmt(&'a Stmt),
    Expr(&'a Expr),
}
#[derive(Default)]
struct Children<'a> {
    nodes: Vec<Node<'a>>,
}
impl<'a> Visitor<'a> for Children<'a> {
    fn visit_stmt(&mut self, n: &'a Stmt) {
        self.nodes.push(Node::Stmt(n));
    }
    fn visit_expr(&mut self, n: &'a Expr) {
        self.nodes.push(Node::Expr(n));
    }
    fn visit_comprehension(&mut self, n: &'a py::Comprehension) {
        self.visit_expr(&n.target);
        self.visit_expr(&n.iter);
        for expr in &n.ifs {
            self.visit_expr(expr);
        }
    }
}
fn calls(file: &PythonFile, body: &[Stmt]) -> Vec<(String, usize)> {
    let mut pending = body.iter().map(Node::Stmt).collect::<Vec<_>>();
    let mut out = Vec::new();
    while let Some(node) = pending.pop() {
        let mut children = Children::default();
        match node {
            Node::Stmt(Stmt::FunctionDef(_) | Stmt::ClassDef(_)) | Node::Expr(Expr::Lambda(_)) => {
                continue;
            }
            Node::Stmt(n) => match n {
                Stmt::Assign(n) => {
                    for t in &n.targets {
                        children.visit_expr(t);
                    }
                    children.visit_expr(&n.value);
                }
                Stmt::AugAssign(n) => {
                    children.visit_expr(&n.target);
                    children.visit_expr(&n.value);
                }
                Stmt::AnnAssign(n) => {
                    children.visit_expr(&n.target);
                    children.visit_expr(&n.annotation);
                    if let Some(v) = &n.value {
                        children.visit_expr(v);
                    }
                }
                Stmt::For(n) => {
                    children.visit_expr(&n.target);
                    children.visit_expr(&n.iter);
                    children.visit_body(&n.body);
                    children.visit_body(&n.orelse);
                }
                _ => visitor::walk_stmt(&mut children, n),
            },
            Node::Expr(n) => {
                if let Expr::Call(call) = n {
                    let name = match call.func.as_ref() {
                        Expr::Name(n) => Some(n.id.to_string()),
                        Expr::Attribute(n) => Some(n.attr.to_string()),
                        _ => None,
                    };
                    if let Some(name) = name {
                        out.push((name, line(file, n.range().start().to_usize())));
                    }
                }
                match n {
                    Expr::Named(n) => {
                        children.visit_expr(&n.target);
                        children.visit_expr(&n.value);
                    }
                    Expr::Dict(n) => {
                        for item in &n.items {
                            if let Some(k) = &item.key {
                                children.visit_expr(k);
                            }
                        }
                        for item in &n.items {
                            children.visit_expr(&item.value);
                        }
                    }
                    Expr::ListComp(n) => {
                        children.visit_expr(&n.elt);
                        for g in &n.generators {
                            children.visit_comprehension(g);
                        }
                    }
                    Expr::SetComp(n) => {
                        children.visit_expr(&n.elt);
                        for g in &n.generators {
                            children.visit_comprehension(g);
                        }
                    }
                    Expr::Generator(n) => {
                        children.visit_expr(&n.elt);
                        for g in &n.generators {
                            children.visit_comprehension(g);
                        }
                    }
                    Expr::DictComp(n) => {
                        children.visit_expr(&n.key);
                        children.visit_expr(&n.value);
                        for g in &n.generators {
                            children.visit_comprehension(g);
                        }
                    }
                    _ => visitor::walk_expr(&mut children, n),
                }
            }
        }
        pending.extend(children.nodes);
    }
    out
}
fn preview(
    symbol: &Symbol,
    symbols: &[Symbol],
    lines: &[String],
    question: &str,
) -> Result<Preview> {
    let start = symbol.line;
    let end = if symbol.kind == "module" {
        lines.len()
    } else {
        symbol.end_line
    };
    if start < 1 || start > end || end > lines.len() {
        return Err(invalid("assessed owner is outside source"));
    }
    let mut spans = Vec::new();
    if end - start < 16 && lines[start - 1..end].join("\n").chars().count() <= 4000 {
        spans.push((start, end));
    } else {
        let query = reasoners::terms(question);
        let prefix = format!("{}.", symbol.qualname);
        let mut members = symbols
            .iter()
            .filter(|s| {
                if symbol.kind == "class" {
                    s.qualname
                        .strip_prefix(&prefix)
                        .is_some_and(|tail| !tail.contains('.'))
                } else if symbol.kind == "module" {
                    s.kind != "module" && !s.qualname.contains('.')
                } else {
                    false
                }
            })
            .collect::<Vec<_>>();
        if members.is_empty() {
            members.push(symbol);
        }
        let mut best: Option<(usize, usize, &Symbol, usize)> = None;
        for owner in members {
            let a = if owner.implementation_line == 0 {
                owner.line
            } else {
                owner.implementation_line
            };
            let b = if owner.kind == "module" {
                end
            } else {
                owner.end_line
            };
            if a < 1 || b < a || b > lines.len() {
                continue;
            }
            let width = 12.min(b - a + 1);
            for first in a..=b - width + 1 {
                let text = lines[first - 1..first + width - 1].join("\n");
                let score = query.intersection(&reasoners::terms(&text)).count();
                if best
                    .as_ref()
                    .is_none_or(|(s, prior, _, _)| score > *s || score == *s && first < *prior)
                {
                    best = Some((score, first, owner, width));
                }
            }
        }
        spans.push((start, (start + 1).min(end)));
        if let Some((_, a, owner, width)) = best {
            if owner.qualname != symbol.qualname || owner.kind != symbol.kind {
                spans.push((owner.line, (owner.line + 1).min(owner.end_line)));
            }
            spans.push((a, a + width - 1));
        }
    }
    let numbers = spans
        .into_iter()
        .flat_map(|(a, b)| a..=b)
        .collect::<BTreeSet<_>>();
    let mut selected = Vec::new();
    let mut chars = 0;
    for n in numbers {
        let cost = lines[n - 1].chars().count() + 1;
        if selected.len() < 16 && chars + cost <= 4000 {
            selected.push(n);
            chars += cost;
        }
    }
    let mut snippets: Vec<Snippet> = Vec::new();
    for &n in &selected {
        if let Some(last) = snippets.last_mut().filter(|s| s.end_line == n - 1) {
            last.end_line = n;
            let mut points = last.content.codepoints().to_vec();
            points.push(10);
            points.extend(lines[n - 1].chars().map(u32::from));
            last.content = PythonText::from_codepoints(points).expect("existing code points");
        } else {
            snippets.push(Snippet {
                start_line: n,
                end_line: n,
                content: lines[n - 1].clone().into(),
            });
        }
    }
    let unavailable = snippets
        .is_empty()
        .then(|| "Source exceeds preview budget; use ken_read for this symbol.".into());
    Ok(Preview {
        end_line: end,
        truncated: selected.len() < end - start + 1,
        snippets,
        preview_unavailable: unavailable,
    })
}
