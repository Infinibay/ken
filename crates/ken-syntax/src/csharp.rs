//! C# type/member ownership, XML documentation and using directives.
use crate::{
    SyntaxNode,
    helpers::{child_text, symbol, text, trim},
    model::{ParsedFile, ParsedImport},
};
use regex::Regex;
use std::sync::OnceLock;

fn type_kind(kind: &str) -> Option<&'static str> {
    match kind {
        "class_declaration" => Some("class"),
        "interface_declaration" => Some("interface"),
        "struct_declaration" => Some("struct"),
        "enum_declaration" => Some("enum"),
        "record_declaration" => Some("record"),
        "delegate_declaration" => Some("delegate"),
        _ => None,
    }
}
pub(crate) fn extract(source: &[u8], root: SyntaxNode<'_>) -> ParsedFile {
    let mut out = ParsedFile::default();
    walk(root, source, "", &mut out);
    out
}
fn walk(node: SyntaxNode<'_>, source: &[u8], owner: &str, out: &mut ParsedFile) {
    for child in node.children() {
        if let Some(kind) = type_kind(child.kind()) {
            declaration(child, source, kind, owner, out);
        } else if child.kind() == "using_directive" {
            let raw = text(child, source);
            let mut value = trim(trim(&raw).trim_end_matches(';'));
            for keyword in ["global", "using", "static", "unsafe"] {
                value = trim(value.strip_prefix(keyword).unwrap_or(value));
            }
            if let Some((_, right)) = value.split_once('=') {
                value = trim(right);
            }
            if !value.is_empty() {
                out.imports.push(ParsedImport {
                    module: value.into(),
                    line: child.start_point()[0] + 1,
                });
            }
        } else if child.is_named() {
            walk(child, source, owner, out);
        }
    }
}
fn declaration(node: SyntaxNode<'_>, source: &[u8], kind: &str, owner: &str, out: &mut ParsedFile) {
    let Some(name) = child_text(node, "name", source).filter(|n| !n.is_empty()) else {
        return;
    };
    let item = symbol(node, kind, name, owner, documentation(node, source));
    let owner = item.qualname.clone();
    out.symbols.push(item);
    let body = node.field("body").or_else(|| {
        node.named_children()
            .into_iter()
            .find(|n| n.kind() == "declaration_list")
    });
    if let Some(body) = body {
        for member in body.named_children() {
            let kind = match member.kind() {
                "method_declaration" => Some("method"),
                "constructor_declaration" => Some("constructor"),
                "property_declaration" => Some("property"),
                _ => None,
            };
            if let Some(kind) = kind {
                if let Some(name) = child_text(member, "name", source).filter(|n| !n.is_empty()) {
                    out.symbols.push(symbol(
                        member,
                        kind,
                        name,
                        &owner,
                        documentation(member, source),
                    ));
                }
            } else if let Some(kind) = type_kind(member.kind()) {
                declaration(member, source, kind, &owner, out);
            }
        }
    }
}
fn documentation(node: SyntaxNode<'_>, source: &[u8]) -> Option<String> {
    static TAGS: OnceLock<Regex> = OnceLock::new();
    let tags = TAGS.get_or_init(|| Regex::new("<[^>]+>").expect("XML doc tags"));
    let mut previous = node.previous_named_sibling();
    let mut comments = Vec::new();
    while let Some(node) = previous.filter(|n| n.kind() == "comment") {
        let value = text(node, source);
        let value = trim(&value);
        if !value.starts_with("///") {
            break;
        }
        comments.push(value.to_owned());
        previous = node.previous_named_sibling();
    }
    comments.into_iter().rev().find_map(|value| {
        let value = tags.replace_all(trim(value.trim_start_matches('/')), "");
        let value = trim(&value);
        (!value.is_empty()).then(|| value.into())
    })
}
