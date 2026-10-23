//! C function definitions and known kernel macros keep original byte coordinates.
use crate::{
    ParseError, SyntaxNode,
    helpers::{qualified, text},
    model::{ParsedFile, ParsedSymbol},
    scopes,
};

pub(crate) fn conditional(kind: &str) -> bool {
    matches!(
        kind,
        "preproc_if" | "preproc_ifdef" | "preproc_else" | "preproc_elif" | "preproc_elifdef"
    )
}
pub(crate) fn extract(source: &[u8], root: SyntaxNode<'_>) -> Result<ParsedFile, ParseError> {
    let mut out = ParsedFile::default();
    definitions(root, source, &mut out, None)?;
    Ok(out)
}
fn definitions(
    container: SyntaxNode<'_>,
    source: &[u8],
    out: &mut ParsedFile,
    owner: Option<&str>,
) -> Result<(), ParseError> {
    for node in container.named_children() {
        if conditional(node.kind()) {
            definitions(node, source, out, owner)?;
            continue;
        }
        let (body, name) = match node.kind() {
            "function_definition" => {
                let Some(body) = node.field("body") else {
                    continue;
                };
                (
                    body,
                    macro_name(node, source)
                        .or_else(|| function_name(node.field("declarator"), source)),
                )
            }
            "expression_statement" => {
                let mut body = node.next_named_sibling();
                while body.is_some_and(|n| n.kind() == "comment") {
                    body = body.and_then(|n| n.next_named_sibling());
                }
                let Some(body) = body.filter(|n| n.kind() == "compound_statement") else {
                    continue;
                };
                (body, macro_name(node, source))
            }
            _ => {
                if owner.is_some() {
                    definitions(node, source, out, owner)?;
                }
                continue;
            }
        };
        if let Some(name) = name.filter(|s| !s.is_empty()) {
            let qualname = qualified(owner.unwrap_or(""), &name);
            let symbol = ParsedSymbol {
                kind: "function".into(),
                name,
                qualname: qualname.clone(),
                line_start: node.start_point()[0] + 1,
                line_end: body.end_point()[0] + 1,
                docstring: None,
            };
            out.symbols.push(symbol.clone());
            out.scopes
                .push(scopes::scope(source, node, symbol, Some(body))?);
            definitions(body, source, out, Some(&qualname))?;
        }
    }
    Ok(())
}
fn function_name(mut node: Option<SyntaxNode<'_>>, source: &[u8]) -> Option<String> {
    let mut callable = false;
    while let Some(current) = node {
        if current.kind() == "identifier" {
            return callable.then(|| text(current, source));
        }
        callable |= current.kind() == "function_declarator";
        node = current.field("declarator").or_else(|| {
            (current.kind() == "parenthesized_declarator")
                .then(|| current.named_children().into_iter().next())
                .flatten()
        });
    }
    None
}
fn macro_name(node: SyntaxNode<'_>, source: &[u8]) -> Option<String> {
    let mut tokens = Vec::new();
    let mut pending = vec![node];
    while !pending.is_empty() && tokens.len() < 3 {
        let current = pending.pop()?;
        if current.kind() == "comment" {
            continue;
        }
        let mut children = current.children();
        if children.is_empty() {
            tokens.push(text(current, source));
        } else {
            children.reverse();
            pending.extend(children);
        }
    }
    if tokens.len() != 3 || tokens[1] != "(" {
        return None;
    }
    let suffix = ["SYSCALL_DEFINE", "COMPAT_SYSCALL_DEFINE", "BPF_CALL_"]
        .into_iter()
        .find_map(|prefix| tokens[0].strip_prefix(prefix))?;
    if suffix.is_empty() || !suffix.chars().all(crate::python_unicode::decimal) {
        return None;
    }
    let mut name = tokens[2].bytes();
    if !name
        .next()
        .is_some_and(|b| b.is_ascii_alphabetic() || b == b'_')
        || !name.all(|b| b.is_ascii_alphanumeric() || b == b'_')
    {
        return None;
    }

    Some(
        if tokens[0].starts_with("SYSCALL_DEFINE") || tokens[0].starts_with("COMPAT_") {
            format!("__{}", tokens[2])
        } else {
            tokens[2].clone()
        },
    )
}
