//! Java type ownership, members and textual import rules.
use crate::{
    SyntaxNode,
    helpers::{block_doc, child_text, symbol, text, trim},
    model::{ParsedFile, ParsedImport},
    scopes,
};

pub(crate) fn extract(source: &[u8], root: SyntaxNode<'_>) -> ParsedFile {
    let mut out = ParsedFile::default();
    walk(root, source, "", &mut out);
    scopes::enrich(source, root, &mut out);
    out
}
fn type_kind(node: SyntaxNode<'_>) -> Option<&'static str> {
    match node.kind() {
        "class_declaration" => Some("class"),
        "interface_declaration" => Some("interface"),
        "enum_declaration" => Some("enum"),
        "record_declaration" => Some("record"),
        _ => None,
    }
}
fn walk(node: SyntaxNode<'_>, source: &[u8], owner: &str, out: &mut ParsedFile) {
    for child in node.children() {
        if let Some(kind) = type_kind(child) {
            declaration(child, source, kind, owner, out);
        } else if child.kind() == "import_declaration" {
            let raw = text(child, source);
            let mut inner =
                trim(trim(raw.strip_prefix("import").unwrap_or(&raw)).trim_end_matches(';'));
            if let Some(rest) = inner.strip_prefix("static") {
                inner = trim(rest);
            }
            let module = trim(inner.trim_end_matches(['.', '*']));
            if !module.is_empty() {
                out.imports.push(ParsedImport {
                    module: module.into(),
                    line: child.start_point()[0] + 1,
                });
            }
        } else if child.is_named() {
            walk(child, source, owner, out);
        }
    }
}
fn declaration(node: SyntaxNode<'_>, source: &[u8], kind: &str, owner: &str, out: &mut ParsedFile) {
    let Some(name) = child_text(node, "name", source).filter(|s| !s.is_empty()) else {
        return;
    };
    let item = symbol(node, kind, name, owner, block_doc(node, source));
    let owner = item.qualname.clone();
    out.symbols.push(item);
    if let Some(body) = node.field("body") {
        for member in body.children() {
            if matches!(
                member.kind(),
                "method_declaration" | "constructor_declaration"
            ) {
                if let Some(name) = child_text(member, "name", source).filter(|s| !s.is_empty()) {
                    out.symbols.push(symbol(
                        member,
                        if member.kind() == "constructor_declaration" {
                            "constructor"
                        } else {
                            "method"
                        },
                        name,
                        &owner,
                        block_doc(member, source),
                    ));
                }
            } else if matches!(
                member.kind(),
                "class_declaration" | "interface_declaration" | "enum_declaration"
            ) {
                declaration(
                    member,
                    source,
                    type_kind(member).expect("matched type"),
                    &owner,
                    out,
                );
            }
        }
    }
}
