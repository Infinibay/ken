//! Markup names, controls and linked source resources.
use crate::{
    SyntaxNode,
    helpers::{lines, symbol, text, trim, whitespace},
    model::{ParsedFile, ParsedImport},
};
use std::collections::BTreeMap;
pub(crate) fn extract(source: &[u8], root: SyntaxNode<'_>) -> ParsedFile {
    let mut out = ParsedFile::default();
    walk(root, source, &mut out);
    out
}
fn walk(node: SyntaxNode<'_>, source: &[u8], out: &mut ParsedFile) {
    for child in node.children() {
        if matches!(child.kind(), "element" | "script_element" | "style_element") {
            element(child, source, out);
        }
        if child.is_named() {
            walk(child, source, out);
        }
    }
}
fn first(node: SyntaxNode<'_>, kind: &str, source: &[u8]) -> Option<String> {
    node.named_children()
        .into_iter()
        .find(|n| n.kind() == kind)
        .map(|n| text(n, source))
}
fn attributes(start: SyntaxNode<'_>, source: &[u8]) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    for attr in start
        .named_children()
        .into_iter()
        .filter(|n| n.kind() == "attribute")
    {
        if let Some(key) = first(attr, "attribute_name", source).filter(|s| !s.is_empty()) {
            let mut value = String::new();
            for child in attr.named_children() {
                if child.kind() == "quoted_attribute_value" {
                    value = first(child, "attribute_value", source).unwrap_or_default();
                    break;
                }
                if child.kind() == "attribute_value" {
                    value = text(child, source);
                    break;
                }
            }
            out.insert(key.to_lowercase(), value);
        }
    }
    out
}
fn doc(node: SyntaxNode<'_>, source: &[u8]) -> Option<String> {
    let sibling = node
        .previous_named_sibling()
        .filter(|n| n.kind() == "comment")?;
    let raw = text(sibling, source);
    let inner = raw.strip_prefix("<!--").unwrap_or(&raw);
    let inner = inner.strip_suffix("-->").unwrap_or(inner);
    lines(inner)
        .map(|s| trim(trim(s).trim_matches('*')))
        .find(|s| !s.is_empty())
        .map(str::to_owned)
}
fn normalise(uri: &str) -> String {
    let uri = trim(uri);
    if uri.is_empty()
        || uri.starts_with(['/', '~', '#'])
        || ["./", "../", "data:", "mailto:"]
            .iter()
            .any(|p| uri.starts_with(p))
        || uri.contains("://")
    {
        uri.to_owned()
    } else {
        format!("./{uri}")
    }
}
fn element(node: SyntaxNode<'_>, source: &[u8], out: &mut ParsedFile) {
    let Some(start) = node
        .named_children()
        .into_iter()
        .find(|n| n.kind() == "start_tag")
        .or_else(|| {
            node.named_children()
                .into_iter()
                .find(|n| n.kind() == "self_closing_tag")
        })
    else {
        return;
    };
    let tag = first(start, "tag_name", source)
        .unwrap_or_default()
        .to_lowercase();
    let attrs = attributes(start, source);
    let documentation = doc(node, source);
    let mut add = |kind, name: String| {
        out.symbols
            .push(symbol(node, kind, name, "", documentation.clone()))
    };
    if tag == "title" {
        let text: String = node
            .named_children()
            .into_iter()
            .filter(|n| matches!(n.kind(), "text" | "raw_text"))
            .map(|n| text(n, source))
            .collect();
        let name = text
            .split(whitespace)
            .filter(|s| !s.is_empty())
            .collect::<Vec<_>>()
            .join(" ");
        if !name.is_empty() {
            add("title", name);
        }
    }
    if let Some(ident) = attrs.get("id").filter(|s| !s.is_empty()) {
        add("anchor", format!("#{ident}"));
    }
    if tag.contains('-') {
        add("component", tag.clone());
    }
    if let Some(name) = attrs.get("name").filter(|s| !s.is_empty())
        && matches!(
            tag.as_str(),
            "form"
                | "input"
                | "select"
                | "textarea"
                | "button"
                | "output"
                | "fieldset"
                | "meta"
                | "param"
                | "map"
                | "iframe"
                | "object"
                | "slot"
        )
    {
        add("control", name.clone());
    }
    let uri = match tag.as_str() {
        "script" => attrs.get("src"),
        "link" => attrs.get("href"),
        _ => None,
    };
    if let Some(uri) = uri.filter(|s| !s.is_empty()) {
        out.imports.push(ParsedImport {
            module: normalise(uri),
            line: node.start_point()[0] + 1,
        });
    }
}
