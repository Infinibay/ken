//! PowerShell declarations and command-shaped module references.
use crate::{
    SyntaxNode,
    helpers::{lines, qualified, symbol, text, trim},
    model::{ParsedFile, ParsedImport},
};
pub(crate) fn extract(source: &[u8], root: SyntaxNode<'_>) -> ParsedFile {
    let mut out = ParsedFile::default();
    walk(root, source, "", &mut out);
    out
}
fn first(node: SyntaxNode<'_>, kind: &str, source: &[u8]) -> Option<String> {
    node.named_children()
        .into_iter()
        .find(|n| n.kind() == kind)
        .map(|n| text(n, source))
}
fn doc(node: SyntaxNode<'_>, source: &[u8]) -> Option<String> {
    let sibling = node
        .previous_named_sibling()
        .filter(|n| n.kind() == "comment")?;
    let raw = text(sibling, source);
    let raw = raw.strip_prefix("<#").unwrap_or(&raw);
    let raw = raw.strip_suffix("#>").unwrap_or(raw);
    lines(raw)
        .map(|s| trim(trim(s).trim_start_matches('#')))
        .find(|s| !s.is_empty() && !s.starts_with('.'))
        .map(str::to_owned)
}
fn walk(node: SyntaxNode<'_>, source: &[u8], owner: &str, out: &mut ParsedFile) {
    for child in node.children() {
        match child.kind() {
            "function_statement" => {
                if let Some(name) = first(child, "function_name", source).filter(|s| !s.is_empty())
                {
                    let kind = if child.children().iter().any(|n| n.kind() == "filter") {
                        "filter"
                    } else if owner.is_empty() {
                        "function"
                    } else {
                        "method"
                    };
                    out.symbols
                        .push(symbol(child, kind, name, owner, doc(child, source)));
                }
            }
            "class_statement" | "enum_statement" => {
                if let Some(name) = first(child, "simple_name", source).filter(|s| !s.is_empty()) {
                    let scope = qualified(owner, &name);
                    let class = child.kind() == "class_statement";
                    out.symbols.push(symbol(
                        child,
                        if class { "class" } else { "enum" },
                        name.clone(),
                        owner,
                        doc(child, source),
                    ));
                    if class {
                        for member in child
                            .named_children()
                            .into_iter()
                            .filter(|n| n.kind() == "class_method_definition")
                        {
                            if let Some(method) =
                                first(member, "simple_name", source).filter(|s| !s.is_empty())
                            {
                                let kind = if method == name {
                                    "constructor"
                                } else {
                                    "method"
                                };
                                out.symbols.push(symbol(
                                    member,
                                    kind,
                                    method,
                                    &scope,
                                    doc(member, source),
                                ));
                            }
                        }
                    }
                }
            }
            "command" => command(child, source, out),
            _ if child.is_named() => walk(child, source, owner, out),
            _ => {}
        }
    }
}
fn clean(raw: &str) -> Option<String> {
    let mut module = trim(trim(raw).trim_matches(['\'', '"'])).replace('\\', "/");
    if module.is_empty() {
        return None;
    }
    for prefix in ["$PSScriptRoot/", "${PSScriptRoot}/", "$PSCommandPath/"] {
        if let Some(tail) = module.strip_prefix(prefix) {
            module = format!("./{tail}");
            break;
        }
    }
    Some(module)
}
fn command(node: SyntaxNode<'_>, source: &[u8], out: &mut ParsedFile) {
    let module = if let Some(operator) = node
        .children()
        .into_iter()
        .find(|n| n.kind() == "command_invokation_operator")
    {
        if trim(&text(operator, source)) != "." {
            return;
        }
        first(node, "command_name_expr", source).and_then(|s| clean(&s))
    } else {
        let cmd = first(node, "command_name", source)
            .map(|s| trim(&s).to_lowercase())
            .unwrap_or_default();
        let args: Vec<_> = node
            .named_children()
            .into_iter()
            .find(|n| n.kind() == "command_elements")
            .into_iter()
            .flat_map(|n| n.named_children())
            .filter(|n| !matches!(n.kind(), "command_argument_sep" | "command_parameter"))
            .map(|n| text(n, source))
            .filter(|s| !s.is_empty())
            .collect();
        if matches!(cmd.as_str(), "import-module" | "ipmo") {
            args.first().and_then(|s| clean(s))
        } else if cmd == "using" && args.len() >= 2 && args[0].to_lowercase() == "module" {
            clean(&args[1])
        } else {
            None
        }
    };
    if let Some(module) = module {
        out.imports.push(ParsedImport {
            module,
            line: node.start_point()[0] + 1,
        });
    }
}
