//! SQL top-level definitions and schema-qualified object identities.
use crate::{
    SyntaxNode,
    helpers::{child_text, symbol, text, trim},
    model::ParsedFile,
};
fn definition(kind: &str) -> Option<(&'static str, bool)> {
    Some(match kind {
        "create_table" => ("table", false),
        "create_view" | "create_materialized_view" => ("view", false),
        "create_function" => ("function", false),
        "create_procedure" => ("procedure", false),
        "create_trigger" => ("trigger", false),
        "create_type" | "create_domain" => ("type", false),
        "create_sequence" => ("sequence", false),
        "create_index" => ("index", true),
        "create_schema" => ("schema", true),
        _ => return None,
    })
}
pub(crate) fn extract(source: &[u8], root: SyntaxNode<'_>) -> ParsedFile {
    let mut out = ParsedFile::default();
    for statement in root
        .children()
        .into_iter()
        .filter(|n| n.kind() == "statement")
    {
        let Some(node) = statement
            .named_children()
            .into_iter()
            .find(|n| definition(n.kind()).is_some())
        else {
            continue;
        };
        let (kind, bare) = definition(node.kind()).unwrap();
        let (name, schema) = if bare {
            (
                node.named_children()
                    .into_iter()
                    .find(|n| n.kind() == "identifier")
                    .map(|n| text(n, source)),
                None,
            )
        } else if let Some(reference) = node
            .named_children()
            .into_iter()
            .find(|n| n.kind() == "object_reference")
        {
            (
                child_text(reference, "name", source),
                child_text(reference, "schema", source),
            )
        } else {
            continue;
        };
        if let Some(name) = name.filter(|s| !s.is_empty()) {
            let mut item = symbol(statement, kind, name.clone(), "", doc(statement, source));
            if let Some(schema) = schema.filter(|s| !s.is_empty()) {
                item.qualname = format!("{schema}.{name}");
            }
            out.symbols.push(item);
        }
    }
    out
}
fn doc(node: SyntaxNode<'_>, source: &[u8]) -> Option<String> {
    let mut sibling = node.previous_named_sibling();
    let mut comments = Vec::new();
    while let Some(node) = sibling.filter(|n| matches!(n.kind(), "comment" | "marginalia")) {
        comments.push(text(node, source));
        sibling = node.previous_named_sibling();
    }
    for raw in comments.into_iter().rev() {
        let mut line = trim(&raw);
        if line.starts_with("--") {
            line = trim(line.trim_start_matches('-'));
        } else if let Some(inner) = line.strip_prefix("/*") {
            line = trim(trim(inner.strip_suffix("*/").unwrap_or(inner)).trim_start_matches('*'));
        }
        if !line.is_empty() {
            return Some(line.to_owned());
        }
    }
    None
}
