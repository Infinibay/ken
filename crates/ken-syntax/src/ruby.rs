//! Ruby lexical owners, constants and load-path calls.
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
fn emit(
    node: SyntaxNode<'_>,
    source: &[u8],
    kind: &str,
    owner: &str,
    out: &mut ParsedFile,
) -> Option<String> {
    let name = child_text(node, "name", source).filter(|s| !s.is_empty())?;
    let item = symbol(node, kind, name, owner, line_doc(node, source, "#"));
    let qualname = item.qualname.clone();
    out.symbols.push(item);
    Some(qualname)
}
fn walk(node: SyntaxNode<'_>, source: &[u8], owner: &str, out: &mut ParsedFile) {
    for child in node.children() {
        match child.kind() {
            "module" | "class" => {
                if let Some(owner) = emit(child, source, child.kind(), owner, out)
                    && let Some(body) = child.field("body")
                {
                    walk(body, source, &owner, out);
                }
            }
            "singleton_class" => {
                if let Some(body) = child.field("body") {
                    walk(body, source, owner, out);
                }
            }
            "method" => {
                emit(
                    child,
                    source,
                    if owner.is_empty() {
                        "function"
                    } else {
                        "method"
                    },
                    owner,
                    out,
                );
            }
            "singleton_method" => {
                emit(child, source, "method", owner, out);
            }
            "assignment" => {
                if let Some(left) = child.field("left").filter(|n| n.kind() == "constant") {
                    let name = text(left, source);
                    if !name.is_empty() {
                        out.symbols.push(symbol(
                            child,
                            "const",
                            name,
                            owner,
                            line_doc(child, source, "#"),
                        ));
                    }
                }
            }
            "call" => require(child, source, out),
            _ if child.is_named() => walk(child, source, owner, out),
            _ => {}
        }
    }
}
fn require(node: SyntaxNode<'_>, source: &[u8], out: &mut ParsedFile) {
    if node.field("receiver").is_some() {
        return;
    }
    let Some(call) = child_text(node, "method", source).filter(|s| {
        matches!(
            s.as_str(),
            "require" | "require_relative" | "load" | "autoload"
        )
    }) else {
        return;
    };
    let Some(args) = node.field("arguments") else {
        return;
    };
    for arg in args.named_children() {
        if arg.kind() != "string" {
            continue;
        }
        let Some(content) = arg
            .named_children()
            .into_iter()
            .find(|n| n.kind() == "string_content")
        else {
            return;
        };
        let raw = text(content, source);
        if raw.is_empty() {
            return;
        }
        let mut path = trim(&raw).to_owned();
        if path.is_empty() {
            return;
        }
        if call == "require_relative" && !path.starts_with(['.', '/']) {
            path = "./".to_owned() + &path;
        }
        out.imports.push(ParsedImport {
            module: path,
            line: node.start_point()[0] + 1,
        });
        return;
    }
}
