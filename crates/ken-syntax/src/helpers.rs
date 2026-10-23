//! Shared source text, declaration names and comment documentation.
use crate::{SyntaxNode, model::ParsedSymbol};

pub(crate) fn text(node: SyntaxNode<'_>, source: &[u8]) -> String {
    String::from_utf8_lossy(&source[node.start_byte()..node.end_byte()]).into_owned()
}
pub(crate) fn child_text(node: SyntaxNode<'_>, field: &str, source: &[u8]) -> Option<String> {
    node.field(field).map(|n| text(n, source))
}
pub(crate) fn whitespace(c: char) -> bool {
    c.is_whitespace() || matches!(c, '\x1c'..='\x1f')
}
pub(crate) fn trim(text: &str) -> &str {
    text.trim_matches(whitespace)
}
pub(crate) fn trim_end(text: &str) -> &str {
    text.trim_end_matches(whitespace)
}
pub(crate) fn lines(text: &str) -> impl Iterator<Item = &str> {
    let mut parts = Vec::new();
    let mut start = 0;
    for (index, separator) in text.match_indices(|c| {
        matches!(
            c,
            '\n' | '\r'
                | '\x0b'
                | '\x0c'
                | '\x1c'
                | '\x1d'
                | '\x1e'
                | '\u{85}'
                | '\u{2028}'
                | '\u{2029}'
        )
    }) {
        if index < start {
            continue;
        } // LF already consumed with the preceding CR.
        parts.push(&text[start..index]);
        start = index + separator.len();
        if separator == "\r" && text.as_bytes().get(start) == Some(&b'\n') {
            start += 1;
        }
    }
    if start < text.len() {
        parts.push(&text[start..]);
    }
    parts.into_iter()
}
pub(crate) fn first_line(text: &str) -> Option<String> {
    lines(text)
        .map(trim)
        .find(|s| !s.is_empty())
        .map(str::to_owned)
}
pub(crate) fn qualified(owner: &str, name: &str) -> String {
    if owner.is_empty() {
        name.into()
    } else {
        format!("{owner}.{name}")
    }
}
pub(crate) fn symbol(
    node: SyntaxNode<'_>,
    kind: &str,
    name: String,
    owner: &str,
    docstring: Option<String>,
) -> ParsedSymbol {
    ParsedSymbol {
        kind: kind.into(),
        qualname: qualified(owner, &name),
        name,
        line_start: node.start_point()[0] + 1,
        line_end: node.end_point()[0] + 1,
        docstring,
    }
}
fn start_sibling(mut node: SyntaxNode<'_>) -> Option<SyntaxNode<'_>> {
    loop {
        if let Some(sibling) = node.previous_named_sibling() {
            return Some(sibling);
        }
        let parent = node.parent()?;
        if !matches!(
            parent.kind(),
            "export_statement" | "ambient_declaration" | "decorated_definition"
        ) {
            return None;
        }
        node = parent;
    }
}
pub(crate) fn line_doc(node: SyntaxNode<'_>, source: &[u8], prefix: &str) -> Option<String> {
    let mut previous = start_sibling(node);
    let mut comments = Vec::new();
    while let Some(node) = previous {
        if !matches!(node.kind(), "line_comment" | "comment") {
            break;
        }
        let raw = text(node, source);
        let raw = raw.trim_start_matches(whitespace);
        let Some(content) = raw.strip_prefix(prefix) else {
            break;
        };
        comments.push(trim(content).to_owned());
        previous = node.previous_named_sibling();
    }
    comments.into_iter().rev().find(|s| !s.is_empty())
}
