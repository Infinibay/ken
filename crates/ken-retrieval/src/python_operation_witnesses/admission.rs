//! Pinned CPython3.12 parse-only limits and lossless literal admission.
use ruff_python_ast::{
    self as py, Expr, InterpolatedStringElement,
    token::TokenKind,
    visitor::{self, Visitor},
};
use ruff_python_parser::{Mode, lexer};
use ruff_text_size::Ranged;
/// Check bracket depth before the recursive parser sees an oversized input.
pub(super) fn lexical_limits(source: &str) -> bool {
    let mut lexer = lexer::lex(source, Mode::Module);
    let mut depth = 0usize;
    loop {
        match lexer.next_token() {
            TokenKind::Lpar | TokenKind::Lsqb | TokenKind::Lbrace => {
                depth += 1;
                if depth > 200 {
                    return false;
                }
            }
            TokenKind::Rpar | TokenKind::Rsqb | TokenKind::Rbrace => {
                depth = depth.saturating_sub(1)
            }
            TokenKind::EndOfFile => return true,
            _ => {}
        }
    }
}
pub(super) fn syntax(module: &py::ModModule, source: &str) -> bool {
    let mut admission = Admission {
        source,
        valid: true,
    };
    admission.visit_body(&module.body);
    admission.valid
}
fn format_depth(elements: &py::InterpolatedStringElements, depth: usize) -> bool {
    elements.iter().all(|part| match part {
        InterpolatedStringElement::Literal(_) => true,
        InterpolatedStringElement::Interpolation(i) => {
            depth < 3
                && i.format_spec
                    .as_ref()
                    .is_none_or(|s| format_depth(&s.elements, depth + 1))
        }
    })
}
struct Admission<'a> {
    source: &'a str,
    valid: bool,
}
impl<'a> Visitor<'a> for Admission<'_> {
    fn visit_expr(&mut self, node: &'a Expr) {
        if let Expr::NumberLiteral(n) = node
            && matches!(n.value, py::Number::Int(_))
        {
            let raw = &self.source[n.range().start().to_usize()..n.range().end().to_usize()];
            // Power-of-two bases are exempt. Leading all-zero decimals are too.
            if raw.bytes().all(|b| b.is_ascii_digit() || b == b'_')
                && raw.bytes().filter(u8::is_ascii_digit).count() > 4300
                && raw.bytes().any(|b| matches!(b, b'1'..=b'9'))
            {
                self.valid = false;
            }
        }
        visitor::walk_expr(self, node);
    }
    fn visit_string_literal(&mut self, literal: &'a py::StringLiteral) {
        self.valid &= ken_syntax::decode_python_string_literal(
            &self.source[literal.range.start().to_usize()..literal.range.end().to_usize()],
        )
        .is_some();
    }
    fn visit_f_string(&mut self, string: &'a py::FString) {
        self.valid &= format_depth(&string.elements, 0);
        visitor::walk_f_string(self, string);
    }
}
