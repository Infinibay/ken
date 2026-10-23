//! Python's compact outline and complete lexical scopes share one syntax tree.
use crate::{
    SyntaxNode,
    helpers::{child_text, first_line, qualified, symbol, text, trim, trim_end},
    model::{ParsedFile, ParsedImport, ParsedScope, ParsedSymbol},
};
use std::collections::BTreeMap;

pub(crate) fn extract(source: &[u8], root: SyntaxNode<'_>) -> ParsedFile {
    let mut parsed = ParsedFile {
        docstring: module_doc(root, source),
        ..Default::default()
    };
    outline(root, source, "", &mut parsed);
    let existing = parsed
        .symbols
        .iter()
        .map(|s| (s.line_start, s.clone()))
        .collect();
    collect_scopes(root, source, "", None, &existing, &mut parsed);
    parsed
}

fn outline(node: SyntaxNode<'_>, source: &[u8], owner: &str, parsed: &mut ParsedFile) {
    for child in node.children() {
        match child.kind() {
            "function_definition" | "class_definition" => {
                let Some(name) = child_text(child, "name", source).filter(|s| !s.is_empty()) else {
                    continue;
                };
                let class = child.kind() == "class_definition";
                let kind = if class {
                    "class"
                } else if owner.is_empty() {
                    "function"
                } else {
                    "method"
                };
                let item = symbol(child, kind, name, owner, doc(child, source, false));
                let qualname = item.qualname.clone();
                parsed.symbols.push(item);
                if class && let Some(body) = child.field("body") {
                    outline(body, source, &qualname, parsed);
                }
            }
            "import_statement" => {
                for import in child.children() {
                    let module = match import.kind() {
                        "dotted_name" => Some(text(import, source)),
                        "aliased_import" => import
                            .children()
                            .into_iter()
                            .find(|n| n.kind() == "dotted_name")
                            .map(|n| text(n, source)),
                        _ => None,
                    };
                    if let Some(module) = module.filter(|s| !s.is_empty()) {
                        parsed.imports.push(ParsedImport {
                            module,
                            line: child.start_point()[0] + 1,
                        });
                    }
                }
            }
            "import_from_statement" => {
                if let Some(import) = child
                    .children()
                    .into_iter()
                    .find(|n| matches!(n.kind(), "dotted_name" | "relative_import"))
                {
                    let module = text(import, source);
                    if !module.is_empty() {
                        parsed.imports.push(ParsedImport {
                            module,
                            line: child.start_point()[0] + 1,
                        });
                    }
                }
            }
            _ => outline(child, source, owner, parsed),
        }
    }
}

fn collect_scopes(
    node: SyntaxNode<'_>,
    source: &[u8],
    owner: &str,
    parent_kind: Option<&str>,
    existing: &BTreeMap<usize, ParsedSymbol>,
    parsed: &mut ParsedFile,
) {
    if matches!(node.kind(), "function_definition" | "class_definition") {
        let Some(name) = child_text(node, "name", source).filter(|s| !s.is_empty()) else {
            return;
        };
        let qualname = qualified(owner, &name);
        let kind = if node.kind() == "class_definition" {
            "class"
        } else if parent_kind == Some("class") {
            "method"
        } else {
            "function"
        };
        let item = existing
            .get(&(node.start_point()[0] + 1))
            .cloned()
            .unwrap_or_else(|| symbol(node, kind, name, owner, doc(node, source, false)));
        let body = node.field("body");
        let end = body.map_or(node.end_byte(), |n| n.start_byte());
        let signature =
            trim_end(&String::from_utf8_lossy(&source[node.start_byte()..end])).to_owned();
        let statements = body.map(|b| b.named_children()).unwrap_or_default();
        let implementation_start_line = body.map(|_| {
            let skip_doc = statements.first().is_some_and(|n| {
                n.kind() == "expression_statement"
                    && n.named_children()
                        .first()
                        .is_some_and(|n| matches!(n.kind(), "string" | "concatenated_string"))
            });
            statements
                .iter()
                .skip(usize::from(skip_doc))
                .find(|n| n.kind() != "comment")
                .map_or(item.line_end, |n| n.start_point()[0] + 1)
        });
        parsed.scopes.push(ParsedScope {
            symbol: item,
            signature,
            documentation: doc(node, source, true),
            owner: (!owner.is_empty()).then(|| owner.to_owned()),
            statements: statements
                .iter()
                .map(|n| (n.start_point()[0] + 1, n.end_point()[0] + 1))
                .collect(),
            implementation_start_line,
            annotations: vec![],
        });
        for child in statements {
            collect_scopes(child, source, &qualname, Some(kind), existing, parsed);
        }
        return;
    }
    for child in node.named_children() {
        collect_scopes(child, source, owner, parent_kind, existing, parsed);
    }
}

fn initial_literal(node: SyntaxNode<'_>, source: &[u8]) -> Option<String> {
    for statement in node.children() {
        if statement.kind() != "expression_statement" {
            if statement.is_named() {
                return None;
            }
            continue;
        }
        return statement
            .children()
            .into_iter()
            .find(|n| n.kind() == "string")
            .map(|n| text(n, source));
    }
    None
}
fn clean(raw: &str) -> Option<String> {
    first_line(trim(trim(raw).trim_matches(['\'', '"'])))
}
fn module_doc(root: SyntaxNode<'_>, source: &[u8]) -> Option<String> {
    initial_literal(root, source).and_then(|raw| clean(&raw))
}
fn doc(node: SyntaxNode<'_>, source: &[u8], full: bool) -> Option<String> {
    let raw = initial_literal(node.field("body")?, source)?;
    if !full {
        return clean(&raw);
    }
    let value = crate::python_literal::decode(&raw)?;
    let value = trim(&value);
    (!value.is_empty()).then(|| value.to_owned())
}
