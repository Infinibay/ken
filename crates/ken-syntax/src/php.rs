//! PHP declarations, namespace imports and literal-only include paths.
use crate::{
    SyntaxNode,
    helpers::{block_doc, child_text, symbol, text, trim},
    model::{ParsedFile, ParsedImport},
};
pub(crate) fn extract(source: &[u8], root: SyntaxNode<'_>) -> ParsedFile {
    let mut out = ParsedFile::default();
    walk(root, source, "", &mut out);
    out
}
fn type_kind(kind: &str) -> Option<&'static str> {
    match kind {
        "class_declaration" => Some("class"),
        "interface_declaration" => Some("interface"),
        "trait_declaration" => Some("trait"),
        "enum_declaration" => Some("enum"),
        _ => None,
    }
}
fn emit(
    node: SyntaxNode<'_>,
    source: &[u8],
    kind: &str,
    owner: &str,
    out: &mut ParsedFile,
) -> Option<String> {
    let name = child_text(node, "name", source).filter(|s| !s.is_empty())?;
    let item = symbol(node, kind, name, owner, block_doc(node, source));
    let owner = item.qualname.clone();
    out.symbols.push(item);
    Some(owner)
}
fn walk(node: SyntaxNode<'_>, source: &[u8], owner: &str, out: &mut ParsedFile) {
    for child in node.children() {
        if let Some(kind) = type_kind(child.kind()) {
            if let Some(owner) = emit(child, source, kind, owner, out)
                && let Some(body) = child.field("body")
            {
                for member in body
                    .named_children()
                    .into_iter()
                    .filter(|n| n.kind() == "method_declaration")
                {
                    emit(member, source, "method", &owner, out);
                }
            }
        } else {
            match child.kind() {
                "function_definition" => {
                    emit(child, source, "function", owner, out);
                }
                "namespace_use_declaration" => using(child, source, out),
                "require_expression"
                | "require_once_expression"
                | "include_expression"
                | "include_once_expression" => {
                    if let Some(string) = child
                        .named_children()
                        .into_iter()
                        .find(|n| n.kind() == "string")
                        && let Some(content) = string
                            .named_children()
                            .into_iter()
                            .find(|n| n.kind() == "string_content")
                    {
                        let module = text(content, source);
                        if !module.is_empty() {
                            out.imports.push(ParsedImport {
                                module,
                                line: child.start_point()[0] + 1,
                            });
                        }
                    }
                }
                _ if child.is_named() => walk(child, source, owner, out),
                _ => {}
            }
        }
    }
}
fn clause_name(node: SyntaxNode<'_>, source: &[u8]) -> Option<String> {
    // The original binding allocates a fresh field node, so its `is alias`
    // comparison never removes a cached child. Preserve first-name selection.
    node.named_children()
        .into_iter()
        .find(|n| matches!(n.kind(), "qualified_name" | "namespace_name" | "name"))
        .map(|n| trim(&text(n, source)).to_owned())
}
fn using(node: SyntaxNode<'_>, source: &[u8], out: &mut ParsedFile) {
    let group = node.field("body").or_else(|| {
        node.named_children()
            .into_iter()
            .find(|n| n.kind() == "namespace_use_group")
    });
    if let Some(group) = group {
        let prefix = node
            .named_children()
            .into_iter()
            .find(|n| n.kind() == "namespace_name")
            .map(|n| text(n, source).trim_end_matches('\\').to_owned())
            .unwrap_or_default();
        for clause in group
            .named_children()
            .into_iter()
            .filter(|n| n.kind() == "namespace_use_clause")
        {
            if let Some(tail) = clause_name(clause, source).filter(|s| !s.is_empty()) {
                out.imports.push(ParsedImport {
                    module: if prefix.is_empty() {
                        tail
                    } else {
                        prefix.clone() + "\\" + &tail
                    },
                    line: node.start_point()[0] + 1,
                });
            }
        }
        return;
    }
    for clause in node
        .named_children()
        .into_iter()
        .filter(|n| n.kind() == "namespace_use_clause")
    {
        if let Some(module) = clause_name(clause, source).filter(|s| !s.is_empty()) {
            out.imports.push(ParsedImport {
                module,
                line: node.start_point()[0] + 1,
            });
        }
    }
}
