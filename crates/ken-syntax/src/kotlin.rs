//! Kotlin type/object ownership and grammar-specific KDoc extraction.
use crate::{
    SyntaxNode,
    helpers::{lines, symbol, text, trim},
    model::{ParsedFile, ParsedImport},
};
pub(crate) fn extract(source: &[u8], root: SyntaxNode<'_>) -> ParsedFile {
    let mut out = ParsedFile::default();
    walk(root, source, "", &mut out);
    out
}
fn name(node: SyntaxNode<'_>, source: &[u8], kind: &str) -> Option<String> {
    node.named_children()
        .into_iter()
        .find(|n| n.kind() == kind)
        .map(|n| text(n, source))
}
fn documentation(node: SyntaxNode<'_>, source: &[u8]) -> Option<String> {
    let previous = node
        .previous_named_sibling()
        .filter(|n| n.kind() == "multiline_comment")?;
    let raw = text(previous, source);
    let inner = raw.strip_prefix("/**")?;
    let inner = inner.strip_suffix("*/").unwrap_or(inner);
    lines(inner)
        .map(|line| trim(trim(line).trim_start_matches('*')))
        .find(|s| !s.is_empty() && !s.starts_with('@'))
        .map(str::to_owned)
}
fn emit(
    node: SyntaxNode<'_>,
    source: &[u8],
    kind: &str,
    name: String,
    owner: &str,
    out: &mut ParsedFile,
) -> String {
    let item = symbol(node, kind, name, owner, documentation(node, source));
    let qualified = item.qualname.clone();
    out.symbols.push(item);
    qualified
}
fn walk(node: SyntaxNode<'_>, source: &[u8], owner: &str, out: &mut ParsedFile) {
    for child in node.children() {
        match child.kind() {
            "class_declaration" | "object_declaration" | "companion_object" => {
                let default = if child.kind() == "companion_object" {
                    Some("Companion".into())
                } else {
                    None
                };
                let Some(name) = name(child, source, "type_identifier")
                    .filter(|s| !s.is_empty())
                    .or(default)
                else {
                    continue;
                };
                let kind = if child.kind() != "class_declaration" {
                    "object"
                } else {
                    let tokens = child.children();
                    if tokens
                        .iter()
                        .any(|n| !n.is_named() && n.kind() == "interface")
                    {
                        "interface"
                    } else if tokens.iter().any(|n| !n.is_named() && n.kind() == "enum") {
                        "enum"
                    } else {
                        "class"
                    }
                };
                let owner = emit(child, source, kind, name, owner, out);
                if let Some(body) = child
                    .named_children()
                    .into_iter()
                    .find(|n| matches!(n.kind(), "class_body" | "enum_class_body"))
                {
                    walk(body, source, &owner, out);
                }
            }
            "function_declaration" => {
                if let Some(name) =
                    name(child, source, "simple_identifier").filter(|s| !s.is_empty())
                {
                    emit(
                        child,
                        source,
                        if owner.is_empty() {
                            "function"
                        } else {
                            "method"
                        },
                        name,
                        owner,
                        out,
                    );
                }
            }
            "secondary_constructor" | "primary_constructor" if !owner.is_empty() => {
                let name = owner.rsplit('.').next().unwrap_or(owner).to_owned();
                let mut item = symbol(
                    child,
                    "constructor",
                    name,
                    owner,
                    documentation(child, source),
                );
                item.qualname = format!("{owner}.<init>");
                out.symbols.push(item);
            }
            "secondary_constructor" | "primary_constructor" => {}
            "type_alias" => {
                if let Some(name) = name(child, source, "type_identifier").filter(|s| !s.is_empty())
                {
                    emit(child, source, "typealias", name, owner, out);
                }
            }
            "import_list" => {
                for header in child
                    .named_children()
                    .into_iter()
                    .filter(|n| n.kind() == "import_header")
                {
                    if let Some(module) =
                        name(header, source, "identifier").filter(|s| !s.is_empty())
                    {
                        out.imports.push(ParsedImport {
                            module,
                            line: header.start_point()[0] + 1,
                        });
                    }
                }
            }
            _ if child.is_named() => walk(child, source, owner, out),
            _ => {}
        }
    }
}
