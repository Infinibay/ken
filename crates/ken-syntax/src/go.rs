//! Go declarations and grouped imports retain receiver and source-line rules.
use crate::{
    SyntaxNode,
    helpers::{child_text, line_doc, symbol, text, trim},
    model::{ParsedFile, ParsedImport},
    scopes,
};

pub(crate) fn extract(source: &[u8], root: SyntaxNode<'_>) -> ParsedFile {
    let mut out = ParsedFile::default();
    walk(root, source, &mut out);
    scopes::enrich(source, root, &mut out);
    out
}
fn walk(node: SyntaxNode<'_>, source: &[u8], out: &mut ParsedFile) {
    for child in node.children() {
        match child.kind() {
            "function_declaration" | "method_declaration" => {
                if let Some(name) = child_text(child, "name", source).filter(|s| !s.is_empty()) {
                    let method = child.kind() == "method_declaration";
                    let receiver = if method {
                        receiver(child, source)
                    } else {
                        None
                    };
                    out.symbols.push(symbol(
                        child,
                        if method { "method" } else { "function" },
                        name,
                        receiver.as_deref().unwrap_or(""),
                        line_doc(child, source, "//"),
                    ));
                }
            }
            "type_declaration" => {
                for spec in child
                    .children()
                    .into_iter()
                    .filter(|n| n.kind() == "type_spec")
                {
                    if let Some(name) = child_text(spec, "name", source).filter(|s| !s.is_empty())
                        && let Some(kind) = spec.field("type")
                    {
                        let kind = match kind.kind() {
                            "struct_type" => "struct",
                            "interface_type" => "interface",
                            _ => "type",
                        };
                        out.symbols.push(symbol(
                            spec,
                            kind,
                            name,
                            "",
                            line_doc(child, source, "//"),
                        ));
                    }
                }
            }
            "import_declaration" => {
                for part in child.children() {
                    match part.kind() {
                        "import_spec" => import(part, source, out),
                        "import_spec_list" => {
                            for spec in part
                                .children()
                                .into_iter()
                                .filter(|n| n.kind() == "import_spec")
                            {
                                import(spec, source, out)
                            }
                        }
                        "interpreted_string_literal" => {
                            let module = text(part, source).trim_matches('"').to_owned();
                            if !module.is_empty() {
                                out.imports.push(ParsedImport {
                                    module,
                                    line: child.start_point()[0] + 1,
                                });
                            }
                        }
                        _ => {}
                    }
                }
            }
            _ if child.is_named() => walk(child, source, out),
            _ => {}
        }
    }
}
fn receiver(node: SyntaxNode<'_>, source: &[u8]) -> Option<String> {
    for receiver in node
        .field("receiver")?
        .children()
        .into_iter()
        .filter(|n| n.kind() == "parameter_declaration")
    {
        if let Some(kind) = receiver.field("type") {
            match kind.kind() {
                "type_identifier" => return Some(text(kind, source)),
                "pointer_type" => {
                    let raw = text(kind, source);
                    let raw = trim(raw.trim_start_matches('*'));
                    return (!raw.is_empty()).then(|| raw.into());
                }
                _ => {}
            }
        }
    }
    None
}
fn import(node: SyntaxNode<'_>, source: &[u8], out: &mut ParsedFile) {
    if let Some(module) = child_text(node, "path", source)
        .map(|s| s.trim_matches('"').to_owned())
        .filter(|s| !s.is_empty())
    {
        out.imports.push(ParsedImport {
            module,
            line: node.start_point()[0] + 1,
        });
    }
}
