//! JavaScript / JSX walker.
//!
//! Symbols emitted: `function_declaration`, `class_declaration` (+ its
//! `method_definition` children), `generator_function_declaration`. The
//! `export_statement` wrapper is handled by emitting from its inner
//! declaration with the export-statement's byte range so `export` shows up
//! in the chunk text.
//!
//! Imports come from `import_statement.source` with the same namespacing
//! convention as TS: `./foo`, `../foo`, `/foo` → `js:./foo`, otherwise
//! `npm:<spec>`. We use the `js:` namespace (rather than `ts:`) so cross-
//! references can later resolve relative paths against the same workspace
//! without conflating module systems.

use tree_sitter::{Node, Parser};

use super::{field_text, node_text, recompute_line_start, Extracted, Symbol};
use crate::ingest::IngestError;

pub(super) fn extract(source: &str) -> crate::ingest::IngestResult<Extracted> {
    let mut parser = Parser::new();
    let language: tree_sitter::Language = tree_sitter_javascript::LANGUAGE.into();
    parser
        .set_language(&language)
        .map_err(|e| IngestError::Unsupported(format!("set js language: {e}")))?;
    let tree = parser
        .parse(source.as_bytes(), None)
        .ok_or_else(|| IngestError::Decode("js parse returned None".into()))?;
    let mut walker = JsWalker { source, symbols: Vec::new(), imports: Vec::new() };
    walker.walk(tree.root_node(), &mut Vec::new(), false, None);
    Ok(Extracted { symbols: walker.symbols, imports: walker.imports })
}

struct JsWalker<'a> {
    source: &'a str,
    symbols: Vec<Symbol>,
    imports: Vec<String>,
}

impl<'a> JsWalker<'a> {
    fn walk(
        &mut self,
        node: Node,
        scope: &mut Vec<String>,
        in_class: bool,
        outer_start: Option<usize>,
    ) {
        match node.kind() {
            "export_statement" => {
                let outer = node.start_byte();
                let effective = find_jsdoc_before(node, self.source).unwrap_or(outer);
                let mut cursor = node.walk();
                for child in node.children(&mut cursor) {
                    if matches!(
                        child.kind(),
                        "function_declaration"
                            | "generator_function_declaration"
                            | "class_declaration"
                    ) {
                        self.walk(child, scope, in_class, Some(effective));
                    }
                }
                return;
            }
            "function_declaration" | "generator_function_declaration" => {
                self.emit_symbol(node, scope, in_class, "fn", outer_start);
                return;
            }
            "class_declaration" => {
                self.emit_symbol(node, scope, false, "class", outer_start);
                if let Some(name) = field_text(node, "name", self.source) {
                    scope.push(name);
                    if let Some(body) = node.child_by_field_name("body") {
                        let mut cursor = body.walk();
                        for child in body.children(&mut cursor) {
                            if child.kind() == "method_definition" {
                                self.emit_symbol(child, scope, true, "fn", None);
                            }
                        }
                    }
                    scope.pop();
                }
                return;
            }
            "import_statement" => {
                self.collect_import(node);
                return;
            }
            _ => {}
        }
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            self.walk(child, scope, in_class, None);
        }
    }

    fn emit_symbol(
        &mut self,
        node: Node,
        scope: &mut Vec<String>,
        is_method: bool,
        kind_tag: &'static str,
        outer_start: Option<usize>,
    ) {
        let name = field_text(node, "name", self.source).unwrap_or_else(|| "<anon>".to_string());
        let qn = qualify_dot(scope, &name);
        let chunk_start = match outer_start {
            Some(s) => s,
            None => find_jsdoc_before(node, self.source).unwrap_or(node.start_byte()),
        };
        let end_byte = node.end_byte();
        let line_start = recompute_line_start(self.source, chunk_start);
        let line_end = (node.end_position().row as u32) + 1;
        let text = self.source[chunk_start..end_byte].to_string();
        self.symbols.push(Symbol {
            qualified_name: qn,
            line_start,
            line_end,
            text,
            kind_tag,
            is_method,
        });
    }

    fn collect_import(&mut self, node: Node) {
        let Some(source_node) = node.child_by_field_name("source") else { return };
        let raw = node_text(source_node, self.source);
        let stripped = raw.trim().trim_matches('"').trim_matches('\'');
        let prefixed = if stripped.starts_with("./")
            || stripped.starts_with("../")
            || stripped.starts_with('/')
        {
            format!("js:{stripped}")
        } else if !stripped.is_empty() {
            format!("npm:{stripped}")
        } else {
            return;
        };
        if !self.imports.iter().any(|p| p == &prefixed) {
            self.imports.push(prefixed);
        }
    }
}

fn find_jsdoc_before(node: Node, source: &str) -> Option<usize> {
    let mut start: Option<usize> = None;
    let mut cursor = node;
    while let Some(prev) = cursor.prev_sibling() {
        if prev.kind() == "comment" {
            let text = node_text(prev, source);
            if text.starts_with("/**") {
                start = Some(prev.start_byte());
                cursor = prev;
                continue;
            }
        }
        break;
    }
    start
}

fn qualify_dot(scope: &[String], name: &str) -> String {
    if scope.is_empty() {
        return name.to_string();
    }
    let mut parts: Vec<String> = scope.to_vec();
    parts.push(name.to_string());
    parts.join(".")
}
