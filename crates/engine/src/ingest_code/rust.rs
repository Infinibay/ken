//! Rust walker. Symbol kinds: `function_item`, `struct_item`, `enum_item`,
//! `trait_item`, `type_item`, `union_item`, `mod_item`, `impl_item`. Imports
//! come from `use_declaration`. Doc comments (`///`, `//!`, `/**`, `/*!`) and
//! `#[...]` attributes preceding a symbol are folded into the symbol's
//! chunk text — they are semantic siblings of the symbol and high-signal
//! for retrieval.

use tree_sitter::{Node, Parser};

use super::{field_text, node_text, recompute_line_start, Extracted, Symbol};
use crate::ingest::IngestError;

pub(super) fn extract(source: &str) -> crate::ingest::IngestResult<Extracted> {
    let mut parser = Parser::new();
    let language: tree_sitter::Language = tree_sitter_rust::LANGUAGE.into();
    parser
        .set_language(&language)
        .map_err(|e| IngestError::Unsupported(format!("set rust language: {e}")))?;
    let tree = parser
        .parse(source.as_bytes(), None)
        .ok_or_else(|| IngestError::Decode("rust parse returned None".into()))?;
    let mut walker = RustWalker { source, symbols: Vec::new(), imports: Vec::new() };
    walker.walk(tree.root_node(), &mut Vec::new());
    Ok(Extracted { symbols: walker.symbols, imports: walker.imports })
}

struct RustWalker<'a> {
    source: &'a str,
    symbols: Vec<Symbol>,
    imports: Vec<String>,
}

impl<'a> RustWalker<'a> {
    fn walk(&mut self, node: Node, scope: &mut Vec<String>) {
        let kind = node.kind();
        match kind {
            "function_item" => {
                if let Some(name) = field_text(node, "name", self.source) {
                    let qn = qualify(scope, &name);
                    let is_method = scope
                        .last()
                        .map(|s| s.starts_with("impl::") || s.starts_with("trait::"))
                        .unwrap_or(false);
                    self.emit(node, qn, "fn", is_method);
                }
            }
            "struct_item" | "enum_item" | "type_item" | "union_item" => {
                if let Some(name) = field_text(node, "name", self.source) {
                    let tag = match kind {
                        "struct_item" => "struct",
                        "enum_item" => "enum",
                        "type_item" => "type",
                        "union_item" => "union",
                        _ => "item",
                    };
                    let qn = qualify(scope, &name);
                    self.emit(node, qn, tag, false);
                }
            }
            "trait_item" => {
                if let Some(name) = field_text(node, "name", self.source) {
                    let qn = qualify(scope, &name);
                    self.emit(node, qn, "trait", false);
                    scope.push(format!("trait::{name}"));
                    self.walk_children(node, scope);
                    scope.pop();
                    return;
                }
            }
            "impl_item" => {
                let target = impl_target_name(self.source, node).unwrap_or_else(|| "<impl>".into());
                scope.push(format!("impl::{target}"));
                self.walk_children(node, scope);
                scope.pop();
                return;
            }
            "mod_item" => {
                if let Some(name) = field_text(node, "name", self.source) {
                    scope.push(name);
                    self.walk_children(node, scope);
                    scope.pop();
                    return;
                }
            }
            "use_declaration" => {
                let path = node_text(node, self.source);
                let cleaned = strip_use_path(path);
                for one in flatten_use(&cleaned) {
                    if one.is_empty() {
                        continue;
                    }
                    let prefixed = format!("rust:{one}");
                    if !self.imports.iter().any(|p| p == &prefixed) {
                        self.imports.push(prefixed);
                    }
                }
                return;
            }
            _ => {}
        }
        self.walk_children(node, scope);
    }

    fn walk_children(&mut self, node: Node, scope: &mut Vec<String>) {
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            self.walk(child, scope);
        }
    }

    fn emit(&mut self, node: Node, qualified_name: String, kind_tag: &'static str, is_method: bool) {
        let (start_byte, end_byte) = expand_with_attrs_and_doc_comments(node, self.source);
        let line_start = recompute_line_start(self.source, start_byte);
        let line_end = (node.end_position().row as u32) + 1;
        let text = self.source[start_byte..end_byte].to_string();
        self.symbols.push(Symbol {
            qualified_name,
            line_start,
            line_end,
            text,
            kind_tag,
            is_method,
        });
    }
}

fn qualify(scope: &[String], name: &str) -> String {
    if scope.is_empty() {
        return name.to_string();
    }
    let mut parts: Vec<String> = scope
        .iter()
        .map(|s| {
            s.strip_prefix("impl::")
                .or_else(|| s.strip_prefix("trait::"))
                .map(str::to_string)
                .unwrap_or_else(|| s.clone())
        })
        .collect();
    parts.push(name.to_string());
    parts.join("::")
}

fn impl_target_name(source: &str, node: Node) -> Option<String> {
    let ty = node.child_by_field_name("type")?;
    Some(node_text(ty, source).to_string())
}

/// Walk previous siblings, consuming consecutive doc comments and
/// `attribute_item`s so the chunk includes both. Stops at the first
/// non-doc, non-attribute sibling (typically `;` or a previous symbol).
fn expand_with_attrs_and_doc_comments(node: Node, source: &str) -> (usize, usize) {
    let mut start = node.start_byte();
    let end = node.end_byte();
    let mut cursor = node;
    while let Some(prev) = cursor.prev_sibling() {
        match prev.kind() {
            "line_comment" => {
                let text = node_text(prev, source);
                if text.starts_with("///") || text.starts_with("//!") {
                    start = prev.start_byte();
                    cursor = prev;
                    continue;
                }
                break;
            }
            "block_comment" => {
                let text = node_text(prev, source);
                if text.starts_with("/**") || text.starts_with("/*!") {
                    start = prev.start_byte();
                    cursor = prev;
                    continue;
                }
                break;
            }
            "attribute_item" | "inner_attribute_item" => {
                start = prev.start_byte();
                cursor = prev;
            }
            _ => break,
        }
    }
    (start, end)
}

fn strip_use_path(text: &str) -> String {
    text.trim()
        .trim_start_matches("use ")
        .trim_end_matches(';')
        .trim()
        .to_string()
}

fn flatten_use(path: &str) -> Vec<String> {
    let path = path.trim();
    if let Some(brace) = path.find('{') {
        let prefix = path[..brace].trim_end_matches("::").trim_end();
        let inner = &path[brace + 1..path.rfind('}').unwrap_or(path.len())];
        let mut out = Vec::new();
        for part in split_top_level_commas(inner) {
            let part = part.trim();
            if part == "self" {
                out.push(prefix.to_string());
            } else if part == "*" {
                continue;
            } else {
                out.extend(flatten_use(&format!("{prefix}::{part}")));
            }
        }
        return out;
    }
    if path.ends_with("::*") {
        return Vec::new();
    }
    let main = path.split(" as ").next().unwrap_or(path).trim();
    if main.is_empty() {
        return Vec::new();
    }
    vec![main.to_string()]
}

fn split_top_level_commas(s: &str) -> Vec<&str> {
    let mut depth = 0i32;
    let mut start = 0usize;
    let mut out = Vec::new();
    for (i, c) in s.char_indices() {
        match c {
            '{' => depth += 1,
            '}' => depth -= 1,
            ',' if depth == 0 => {
                out.push(&s[start..i]);
                start = i + 1;
            }
            _ => {}
        }
    }
    if start < s.len() {
        out.push(&s[start..]);
    }
    out
}
