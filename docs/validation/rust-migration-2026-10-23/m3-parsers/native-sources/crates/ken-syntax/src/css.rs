//! Stylesheet selectors, design tokens and stylesheet references.
use crate::{
    SyntaxNode,
    helpers::{lines, symbol, text, trim, whitespace},
    model::{ParsedFile, ParsedImport},
};
pub(crate) fn extract(source: &[u8], root: SyntaxNode<'_>) -> ParsedFile {
    let mut out = ParsedFile::default();
    walk(root, source, &mut out);
    out
}
fn first(node: SyntaxNode<'_>, kind: &str, source: &[u8]) -> Option<String> {
    node.named_children()
        .into_iter()
        .find(|n| n.kind() == kind)
        .map(|n| text(n, source))
}
fn doc(node: SyntaxNode<'_>, source: &[u8]) -> Option<String> {
    let sibling = node
        .previous_named_sibling()
        .filter(|n| n.kind() == "comment")?;
    let raw = text(sibling, source);
    let inner = raw.strip_prefix("/*").unwrap_or(&raw);
    let inner = inner.strip_suffix("*/").unwrap_or(inner);
    lines(inner)
        .map(|s| trim(trim(s).trim_start_matches('*')))
        .find(|s| !s.is_empty())
        .map(str::to_owned)
}
fn walk(node: SyntaxNode<'_>, source: &[u8], out: &mut ParsedFile) {
    for child in node.children() {
        match child.kind() {
            "import_statement" => {
                if let Some(uri) = uri(child, source).filter(|s| !s.is_empty()) {
                    let uri = trim(&uri);
                    let module = if uri.is_empty()
                        || uri.starts_with(['/', '~'])
                        || uri.starts_with("./")
                        || uri.starts_with("../")
                        || uri.contains("://")
                    {
                        uri.to_owned()
                    } else {
                        format!("./{uri}")
                    };
                    out.imports.push(ParsedImport {
                        module,
                        line: child.start_point()[0] + 1,
                    });
                }
            }
            "rule_set" => {
                if let Some(name) = first(child, "selectors", source).filter(|s| !s.is_empty()) {
                    let name = name
                        .split(whitespace)
                        .filter(|s| !s.is_empty())
                        .collect::<Vec<_>>()
                        .join(" ");
                    if !name.is_empty() {
                        out.symbols
                            .push(symbol(child, "rule", name, "", doc(child, source)));
                    }
                }
                walk(child, source, out);
            }
            "keyframes_statement" => {
                if let Some(name) = first(child, "keyframes_name", source).filter(|s| !s.is_empty())
                {
                    out.symbols
                        .push(symbol(child, "keyframes", name, "", doc(child, source)));
                }
            }
            "declaration" => {
                if let Some(name) =
                    first(child, "property_name", source).filter(|s| s.starts_with("--"))
                {
                    out.symbols.push(symbol(child, "variable", name, "", None));
                }
            }
            _ if child.is_named() => walk(child, source, out),
            _ => {}
        }
    }
}
fn uri(node: SyntaxNode<'_>, source: &[u8]) -> Option<String> {
    for child in node.named_children() {
        if child.kind() == "string_value" {
            return Some(text(child, source).trim_matches(['\'', '"']).to_owned());
        }
        if child.kind() == "call_expression"
            && let Some(args) = child
                .named_children()
                .into_iter()
                .find(|n| n.kind() == "arguments")
            && let Some(arg) = args
                .named_children()
                .into_iter()
                .find(|n| matches!(n.kind(), "string_value" | "plain_value"))
        {
            return Some(text(arg, source).trim_matches(['\'', '"']).to_owned());
        }
    }
    None
}
