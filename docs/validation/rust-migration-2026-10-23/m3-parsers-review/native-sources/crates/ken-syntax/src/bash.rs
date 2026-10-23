//! Shell function ownership and source-command imports.
use crate::{
    SyntaxNode,
    helpers::{child_text, line_doc, symbol, text, trim},
    model::{ParsedFile, ParsedImport},
};
pub(crate) fn extract(source: &[u8], root: SyntaxNode<'_>) -> ParsedFile {
    let mut out = ParsedFile::default();
    walk(root, source, "", &mut out);
    out
}
fn walk(node: SyntaxNode<'_>, source: &[u8], owner: &str, out: &mut ParsedFile) {
    for child in node.children() {
        match child.kind() {
            "function_definition" => {
                if let Some(name) = child_text(child, "name", source).filter(|s| !s.is_empty()) {
                    let item = symbol(
                        child,
                        if owner.is_empty() {
                            "function"
                        } else {
                            "method"
                        },
                        name,
                        owner,
                        line_doc(child, source, "#"),
                    );
                    let scope = item.qualname.clone();
                    out.symbols.push(item);
                    if let Some(body) = child.field("body") {
                        walk(body, source, &scope, out);
                    }
                }
            }
            "command" => {
                if child_text(child, "name", source)
                    .is_some_and(|s| matches!(s.as_str(), "source" | "."))
                    && let Some(arg) = child.field("argument")
                {
                    let module = trim(&text(arg, source))
                        .trim_matches(['\'', '"'])
                        .to_owned();
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
