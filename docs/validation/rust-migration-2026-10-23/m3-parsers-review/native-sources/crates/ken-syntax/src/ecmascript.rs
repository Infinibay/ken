//! ECMAScript outline rules; TypeScript adds only its original declaration kinds.
use crate::{
    ParseError, SyntaxNode, ecmascript_scopes,
    helpers::{block_doc, child_text, symbol, text},
    model::{ParsedFile, ParsedImport},
};

pub(crate) fn extract(
    source: &[u8],
    root: SyntaxNode<'_>,
    typescript: bool,
) -> Result<ParsedFile, ParseError> {
    let mut out = ParsedFile::default();
    walk(root, source, "", typescript, &mut out);
    ecmascript_scopes::enrich(source, root, &mut out)?;
    Ok(out)
}
fn walk(node: SyntaxNode<'_>, source: &[u8], owner: &str, typescript: bool, out: &mut ParsedFile) {
    for child in node.children() {
        match child.kind() {
            "function_declaration" | "generator_function_declaration" => {
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
            "class_declaration" => class(child, source, owner, typescript, out),
            "interface_declaration" | "type_alias_declaration" | "enum_declaration"
                if typescript =>
            {
                let kind = match child.kind() {
                    "interface_declaration" => "interface",
                    "type_alias_declaration" => "type",
                    _ => "enum",
                };
                emit(child, source, kind, owner, out);
            }
            "import_statement" => {
                if let Some(module) = child
                    .field("source")
                    .map(|n| text(n, source))
                    .filter(|s| !s.is_empty())
                {
                    out.imports.push(ParsedImport {
                        module: module.trim_matches(['\'', '"']).into(),
                        line: child.start_point()[0] + 1,
                    });
                }
            }
            "lexical_declaration" | "variable_declaration" => {
                for declarator in child
                    .children()
                    .into_iter()
                    .filter(|n| n.kind() == "variable_declarator")
                {
                    if declarator.field("value").is_none_or(|n| {
                        !matches!(n.kind(), "arrow_function" | "function_expression")
                    }) {
                        continue;
                    }
                    if let Some(name) =
                        child_text(declarator, "name", source).filter(|n| !n.is_empty())
                    {
                        out.symbols.push(symbol(
                            child,
                            "function",
                            name,
                            owner,
                            block_doc(child, source),
                        ));
                    }
                }
            }
            _ if child.is_named() => walk(child, source, owner, typescript, out),
            _ => {}
        }
    }
}
fn emit(node: SyntaxNode<'_>, source: &[u8], kind: &str, owner: &str, out: &mut ParsedFile) {
    if let Some(name) = child_text(node, "name", source).filter(|n| !n.is_empty()) {
        out.symbols
            .push(symbol(node, kind, name, owner, block_doc(node, source)));
    }
}
fn class(node: SyntaxNode<'_>, source: &[u8], owner: &str, typescript: bool, out: &mut ParsedFile) {
    let Some(name) = child_text(node, "name", source).filter(|n| !n.is_empty()) else {
        return;
    };
    let item = symbol(node, "class", name, owner, block_doc(node, source));
    let owner = item.qualname.clone();
    out.symbols.push(item);
    if let Some(body) = node.field("body") {
        for method in body.children() {
            if method.kind() == "method_definition"
                || (typescript
                    && matches!(
                        method.kind(),
                        "method_signature" | "abstract_method_signature"
                    ))
            {
                emit(method, source, "method", &owner, out);
            }
        }
    }
}
