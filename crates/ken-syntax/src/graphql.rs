//! GraphQL schema definitions, members and executable document names.
use crate::{
    SyntaxNode,
    helpers::{lines, symbol, text, trim},
    model::ParsedFile,
};
pub(crate) fn extract(source: &[u8], root: SyntaxNode<'_>) -> ParsedFile {
    let mut out = ParsedFile::default();
    walk(root, source, &mut out);
    out
}
fn name(node: SyntaxNode<'_>, source: &[u8]) -> Option<String> {
    node.children()
        .into_iter()
        .find(|n| n.kind() == "name")
        .map(|n| text(n, source))
        .filter(|s| !s.is_empty())
}
fn description(node: SyntaxNode<'_>, source: &[u8]) -> Option<String> {
    let desc = node
        .named_children()
        .into_iter()
        .find(|n| n.kind() == "description")?;
    let raw = text(desc, source);
    let raw = trim(&raw);
    let inner = if let Some(inner) = raw.strip_prefix("\"\"\"") {
        inner.strip_suffix("\"\"\"").unwrap_or(inner)
    } else if let Some(inner) = raw.strip_prefix('"') {
        if raw.len() > 1 {
            inner.strip_suffix('"').unwrap_or(inner)
        } else {
            inner
        }
    } else {
        raw
    };
    lines(inner)
        .map(trim)
        .find(|s| !s.is_empty())
        .map(str::to_owned)
}
fn type_kind(kind: &str) -> Option<&'static str> {
    match kind {
        "object_type_definition" | "object_type_extension" => Some("type"),
        "interface_type_definition" | "interface_type_extension" => Some("interface"),
        "input_object_type_definition" | "input_object_type_extension" => Some("input"),
        "enum_type_definition" | "enum_type_extension" => Some("enum"),
        "union_type_definition" | "union_type_extension" => Some("union"),
        "scalar_type_definition" | "scalar_type_extension" => Some("scalar"),
        "directive_definition" => Some("directive"),
        _ => None,
    }
}
fn walk(node: SyntaxNode<'_>, source: &[u8], out: &mut ParsedFile) {
    for child in node.children() {
        if let Some(kind) = type_kind(child.kind()) {
            if let Some(scope) = name(child, source) {
                out.symbols.push(symbol(
                    child,
                    kind,
                    scope.clone(),
                    "",
                    description(child, source),
                ));
                members(child, source, &scope, out);
            }
        } else {
            match child.kind() {
                "schema_definition" | "schema_extension" => out.symbols.push(symbol(
                    child,
                    "schema",
                    "schema".into(),
                    "",
                    description(child, source),
                )),
                "operation_definition" => {
                    let kind = child
                        .children()
                        .into_iter()
                        .find(|n| n.kind() == "operation_type")
                        .map(|n| text(n, source))
                        .filter(|s| !s.is_empty())
                        .unwrap_or("operation".into());
                    out.symbols.push(symbol(
                        child,
                        &kind,
                        name(child, source).unwrap_or("<anonymous>".into()),
                        "",
                        None,
                    ));
                }
                "fragment_definition" => {
                    if let Some(name) = child
                        .children()
                        .into_iter()
                        .find(|n| n.kind() == "fragment_name")
                        .and_then(|n| name(n, source))
                    {
                        out.symbols.push(symbol(child, "fragment", name, "", None));
                    }
                }
                _ if child.is_named() => walk(child, source, out),
                _ => {}
            }
        }
    }
}
fn members(node: SyntaxNode<'_>, source: &[u8], owner: &str, out: &mut ParsedFile) {
    for container in node.named_children() {
        let (node_type, kind) = match container.kind() {
            "fields_definition" => ("field_definition", "field"),
            "input_fields_definition" => ("input_value_definition", "field"),
            "enum_values_definition" => ("enum_value_definition", "enum_value"),
            _ => continue,
        };
        for member in container
            .named_children()
            .into_iter()
            .filter(|n| n.kind() == node_type)
        {
            let name = name(member, source).or_else(|| {
                member
                    .children()
                    .into_iter()
                    .find(|n| n.kind() == "enum_value")
                    .and_then(|n| name(n, source))
            });
            if let Some(name) = name {
                out.symbols.push(symbol(
                    member,
                    kind,
                    name,
                    owner,
                    description(member, source),
                ));
            }
        }
    }
}
