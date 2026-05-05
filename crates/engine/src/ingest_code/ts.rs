//! TypeScript / TSX walker.
//!
//! Symbols emitted: `function_declaration`, `class_declaration` (+ its
//! `method_definition` children), `interface_declaration`,
//! `type_alias_declaration`, `enum_declaration`. `export_statement` wraps
//! these — when one is encountered we use the export wrapper's byte range
//! so the chunk text contains the `export`/`export default` modifier.
//!
//! Imports come from `import_statement.source` (the string literal). We
//! split namespace by specifier shape:
//!
//! * `./foo`, `../foo`, `/foo`  →  `ts:./foo`  (relative path, kept verbatim)
//! * `react`, `@scope/pkg`      →  `npm:react`, `npm:@scope/pkg`
//!
//! TS decorators on classes/methods are children of the declaration, so
//! `node.start_byte()..node.end_byte()` already includes them; no special
//! handling needed.

use tree_sitter::{Node, Parser};

use super::{field_text, node_text, recompute_line_start, Extracted, Symbol};
use crate::ingest::IngestError;

pub(super) fn extract(source: &str, jsx: bool) -> crate::ingest::IngestResult<Extracted> {
    let mut parser = Parser::new();
    let language: tree_sitter::Language = if jsx {
        tree_sitter_typescript::LANGUAGE_TSX.into()
    } else {
        tree_sitter_typescript::LANGUAGE_TYPESCRIPT.into()
    };
    parser
        .set_language(&language)
        .map_err(|e| IngestError::Unsupported(format!("set ts language: {e}")))?;
    let tree = parser
        .parse(source.as_bytes(), None)
        .ok_or_else(|| IngestError::Decode("ts parse returned None".into()))?;
    let mut walker = TsWalker { source, symbols: Vec::new(), imports: Vec::new() };
    walker.walk(tree.root_node(), &mut Vec::new(), false, None);
    Ok(Extracted { symbols: walker.symbols, imports: walker.imports })
}

struct TsWalker<'a> {
    source: &'a str,
    symbols: Vec<Symbol>,
    imports: Vec<String>,
}

impl<'a> TsWalker<'a> {
    /// `outer_start` overrides the chunk's start byte when the node is wrapped
    /// in `export_statement` — so we capture `export class Foo` and not just
    /// `class Foo`.
    fn walk(
        &mut self,
        node: Node,
        scope: &mut Vec<String>,
        in_class: bool,
        outer_start: Option<usize>,
    ) {
        match node.kind() {
            "export_statement" => {
                // The JSDoc comment, if any, is a sibling of the
                // `export_statement` (not of the inner declaration), so we
                // resolve it here once and propagate the byte start down.
                let outer = node.start_byte();
                let effective = find_jsdoc_before(node, self.source).unwrap_or(outer);
                let mut cursor = node.walk();
                for child in node.children(&mut cursor) {
                    if matches!(
                        child.kind(),
                        "function_declaration"
                            | "class_declaration"
                            | "abstract_class_declaration"
                            | "interface_declaration"
                            | "type_alias_declaration"
                            | "enum_declaration"
                    ) {
                        self.walk(child, scope, in_class, Some(effective));
                    }
                }
                return;
            }
            "function_declaration" => {
                self.emit_symbol(node, scope, in_class, "fn", outer_start);
                return;
            }
            "class_declaration" | "abstract_class_declaration" => {
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
            "interface_declaration" => {
                self.emit_symbol(node, scope, false, "interface", outer_start);
                return;
            }
            "type_alias_declaration" => {
                self.emit_symbol(node, scope, false, "type", outer_start);
                return;
            }
            "enum_declaration" => {
                self.emit_symbol(node, scope, false, "enum", outer_start);
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
        // outer_start (if set) already accounts for JSDoc of an enclosing
        // export_statement. For un-exported decls and class methods we
        // resolve the JSDoc here against the node's own previous siblings.
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
        // Strip surrounding quotes (`"...", '...'`).
        let stripped = raw.trim().trim_matches('"').trim_matches('\'');
        let prefixed = if stripped.starts_with("./")
            || stripped.starts_with("../")
            || stripped.starts_with('/')
        {
            format!("ts:{stripped}")
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

/// Walk back through `node`'s previous siblings consuming consecutive JSDoc
/// comments (`/** ... */`). Plain `//` and non-JSDoc `/* */` are NOT
/// consumed — they're often non-doc commentary. Returns the byte offset
/// of the earliest JSDoc found, or `None` if there was none.
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
