//! Dart signatures and sibling bodies retain the original declaration spans.
use crate::{
    SyntaxNode,
    helpers::{child_text, lines, symbol, text, trim},
    model::{ParsedFile, ParsedImport},
};
pub(crate) fn extract(source: &[u8], root: SyntaxNode<'_>) -> ParsedFile {
    let mut out = ParsedFile::default();
    walk(root, source, "", &mut out);
    out
}
fn signature(kind: &str) -> bool {
    matches!(
        kind,
        "function_signature"
            | "getter_signature"
            | "setter_signature"
            | "constructor_signature"
            | "factory_constructor_signature"
    )
}
fn constructor(kind: &str) -> bool {
    matches!(
        kind,
        "constructor_signature" | "factory_constructor_signature"
    )
}
fn first_identifier(node: SyntaxNode<'_>, source: &[u8]) -> Option<String> {
    node.named_children()
        .into_iter()
        .find(|n| n.kind() == "identifier")
        .map(|n| text(n, source))
}
fn walk(node: SyntaxNode<'_>, source: &[u8], owner: &str, out: &mut ParsedFile) {
    for child in node.children() {
        match child.kind() {
            "class_definition"
            | "mixin_declaration"
            | "enum_declaration"
            | "extension_declaration" => {
                let extension = child.kind() == "extension_declaration";
                let name = if extension {
                    first_identifier(child, source)
                        .filter(|s| !s.is_empty())
                        .or_else(|| Some("<anonymous>".into()))
                } else {
                    child_text(child, "name", source)
                        .filter(|s| !s.is_empty())
                        .or_else(|| first_identifier(child, source))
                };
                let Some(name) = name.filter(|s| !s.is_empty()) else {
                    continue;
                };
                let kind = match child.kind() {
                    "class_definition" => "class",
                    "mixin_declaration" => "mixin",
                    "enum_declaration" => "enum",
                    _ => "extension",
                };
                let item = symbol(child, kind, name, owner, documentation(child, source));
                let owner = item.qualname.clone();
                out.symbols.push(item);
                let body = child.named_children().into_iter().find(|n| {
                    if extension {
                        n.kind() == "extension_body"
                    } else {
                        n.kind().ends_with("_body")
                    }
                });
                if let Some(body) = body {
                    members(body, source, &owner, out);
                }
            }
            "type_alias" => {
                if let Some(name) = child
                    .named_children()
                    .into_iter()
                    .find(|n| n.kind() == "type_identifier")
                    .map(|n| text(n, source))
                    .filter(|s| !s.is_empty())
                {
                    out.symbols.push(symbol(
                        child,
                        "typedef",
                        name,
                        owner,
                        documentation(child, source),
                    ));
                }
            }
            "function_signature" | "getter_signature" | "setter_signature" => {
                member(child, source, "function", owner, out)
            }
            "import_or_export" => {
                if let Some(module) = uri(child, source).filter(|s| !s.is_empty()) {
                    out.imports.push(ParsedImport {
                        module,
                        line: child.start_point()[0] + 1,
                    });
                }
            }
            _ if child.is_named() => walk(child, source, owner, out),
            _ => {}
        }
    }
}
fn members(body: SyntaxNode<'_>, source: &[u8], owner: &str, out: &mut ParsedFile) {
    for node in body.named_children() {
        if node.kind() == "method_signature" {
            if let Some(inner) = node
                .named_children()
                .first()
                .copied()
                .filter(|n| signature(n.kind()))
            {
                let kind = if constructor(inner.kind()) {
                    "constructor"
                } else {
                    match inner.kind() {
                        "getter_signature" => "getter",
                        "setter_signature" => "setter",
                        _ => "method",
                    }
                };
                member(node, source, kind, owner, out);
            }
        } else if node.kind() == "declaration"
            && node.named_children().iter().any(|n| constructor(n.kind()))
        {
            member(node, source, "constructor", owner, out);
        }
    }
}
fn member(node: SyntaxNode<'_>, source: &[u8], kind: &str, owner: &str, out: &mut ParsedFile) {
    let inner = if matches!(node.kind(), "method_signature" | "declaration") {
        node.named_children()
            .into_iter()
            .find(|n| signature(n.kind()))
            .unwrap_or(node)
    } else {
        node
    };
    let parts: Vec<_> = inner
        .named_children()
        .into_iter()
        .filter(|n| n.kind() == "identifier")
        .map(|n| text(n, source))
        .filter(|s| !s.is_empty())
        .collect();
    if parts.is_empty() {
        return;
    }
    let mut item = symbol(
        node,
        kind,
        parts.join("."),
        owner,
        documentation(node, source),
    );
    if let Some(body) = node
        .next_named_sibling()
        .filter(|n| n.kind() == "function_body")
    {
        item.line_end = body.end_point()[0] + 1;
    }
    out.symbols.push(item);
}
fn uri(node: SyntaxNode<'_>, source: &[u8]) -> Option<String> {
    for child in node.named_children() {
        if child.kind() == "uri" {
            return Some(text(child, source).trim_matches(['\'', '"']).into());
        }
        if let Some(found) = uri(child, source).filter(|s| !s.is_empty()) {
            return Some(found);
        }
    }
    None
}
fn documentation(node: SyntaxNode<'_>, source: &[u8]) -> Option<String> {
    let previous = node
        .previous_named_sibling()
        .filter(|n| n.kind() == "documentation_comment")?;
    let raw = text(previous, source);
    for raw in lines(&raw) {
        let line = trim(raw);
        let line = if let Some(rest) = line
            .strip_prefix("///")
            .or_else(|| line.strip_prefix("/**"))
        {
            trim(rest)
        } else {
            trim(line.trim_start_matches('*').trim_start_matches('/'))
        };
        if !line.is_empty() && !matches!(line, "/**" | "*/") {
            return Some(line.into());
        }
    }
    None
}
