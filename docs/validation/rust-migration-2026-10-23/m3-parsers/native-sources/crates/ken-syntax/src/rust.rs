//! Rust items retain the original method/trait/impl and import identities.
use crate::{
    SyntaxNode,
    helpers::{child_text, line_doc, qualified, symbol, text, trim},
    model::{ParsedFile, ParsedImport},
    scopes,
};

pub(crate) fn extract(source: &[u8], root: SyntaxNode<'_>) -> ParsedFile {
    let mut parsed = ParsedFile::default();
    walk(root, source, "", false, &mut parsed);
    scopes::enrich(source, root, &mut parsed);
    parsed
}
fn walk(node: SyntaxNode<'_>, source: &[u8], owner: &str, in_type: bool, parsed: &mut ParsedFile) {
    let mut pending = node.children();
    pending.reverse();
    while let Some(child) = pending.pop() {
        match child.kind() {
            "function_item" => function(child, source, owner, in_type, parsed),
            "struct_item" | "enum_item" | "trait_item" => {
                let Some(name) = child_text(child, "name", source).filter(|n| !n.is_empty()) else {
                    continue;
                };
                let kind = match child.kind() {
                    "struct_item" => "struct",
                    "enum_item" => "enum",
                    _ => "trait",
                };
                parsed.symbols.push(symbol(
                    child,
                    kind,
                    name.clone(),
                    owner,
                    line_doc(child, source, "///"),
                ));
                if kind == "trait"
                    && let Some(body) = child.field("body")
                {
                    walk(body, source, &qualified(owner, &name), true, parsed);
                }
            }
            "impl_item" => {
                let Some(name) = child_text(child, "type", source).filter(|n| !n.is_empty()) else {
                    continue;
                };
                let bare = trim(name.split('<').next().unwrap_or(""));
                if let Some(body) = child.field("body") {
                    for method in body
                        .children()
                        .into_iter()
                        .filter(|n| n.kind() == "function_item")
                    {
                        function(method, source, bare, true, parsed);
                    }
                }
            }
            "use_declaration" => {
                let module = child_text(child, "argument", source)
                    .filter(|s| !s.is_empty())
                    .unwrap_or_else(|| {
                        let raw = text(child, source);
                        trim(trim(raw.strip_prefix("use").unwrap_or(&raw)).trim_end_matches(';'))
                            .to_owned()
                    });
                if !module.is_empty() {
                    parsed.imports.push(ParsedImport {
                        module: module.split("::{").next().unwrap_or("").into(),
                        line: child.start_point()[0] + 1,
                    });
                }
            }
            _ if child.is_named() => {
                let mut children = child.children();
                children.reverse();
                pending.extend(children);
            }
            _ => {}
        }
    }
}
fn function(
    node: SyntaxNode<'_>,
    source: &[u8],
    owner: &str,
    is_method: bool,
    parsed: &mut ParsedFile,
) {
    let Some(name) = child_text(node, "name", source).filter(|n| !n.is_empty()) else {
        return;
    };
    let item = symbol(
        node,
        if is_method { "method" } else { "function" },
        name,
        owner,
        line_doc(node, source, "///"),
    );
    let owner = item.qualname.clone();
    parsed.symbols.push(item);
    if let Some(body) = node.field("body") {
        walk(body, source, &owner, false, parsed);
    }
}
