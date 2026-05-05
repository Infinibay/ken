//! Python walker. Symbol kinds: `function_definition`, `class_definition`,
//! both wrapped by an optional `decorated_definition` (when decorated). The
//! decorator chain is folded into the chunk so `@dataclass`, `@app.route`
//! etc. live with the symbol they decorate.
//!
//! Imports come from `import_statement` (`import x`, `import a.b as c`)
//! and `import_from_statement` (`from x import a, b`). Wildcards
//! (`from x import *`) are dropped — they don't identify a definite target.

use tree_sitter::{Node, Parser};

use super::{field_text, node_text, recompute_line_start, Extracted, Symbol};
use crate::ingest::IngestError;

pub(super) fn extract(source: &str) -> crate::ingest::IngestResult<Extracted> {
    let mut parser = Parser::new();
    let language: tree_sitter::Language = tree_sitter_python::LANGUAGE.into();
    parser
        .set_language(&language)
        .map_err(|e| IngestError::Unsupported(format!("set python language: {e}")))?;
    let tree = parser
        .parse(source.as_bytes(), None)
        .ok_or_else(|| IngestError::Decode("python parse returned None".into()))?;
    let mut walker = PyWalker { source, symbols: Vec::new(), imports: Vec::new() };
    walker.walk(tree.root_node(), &mut Vec::new(), false);
    Ok(Extracted { symbols: walker.symbols, imports: walker.imports })
}

struct PyWalker<'a> {
    source: &'a str,
    symbols: Vec<Symbol>,
    imports: Vec<String>,
}

impl<'a> PyWalker<'a> {
    fn walk(&mut self, node: Node, scope: &mut Vec<String>, in_class: bool) {
        let kind = node.kind();
        match kind {
            "decorated_definition" => {
                if let Some(inner) = node.child_by_field_name("definition") {
                    let inner_kind = inner.kind();
                    if let Some(name) = field_text(inner, "name", self.source) {
                        let qn = qualify_dot(scope, &name);
                        let line_start = recompute_line_start(self.source, node.start_byte());
                        let line_end = (inner.end_position().row as u32) + 1;
                        let text =
                            self.source[node.start_byte()..node.end_byte()].to_string();
                        match inner_kind {
                            "function_definition" => {
                                self.symbols.push(Symbol {
                                    qualified_name: qn,
                                    line_start,
                                    line_end,
                                    text,
                                    kind_tag: "fn",
                                    is_method: in_class,
                                });
                            }
                            "class_definition" => {
                                self.symbols.push(Symbol {
                                    qualified_name: qn,
                                    line_start,
                                    line_end,
                                    text,
                                    kind_tag: "class",
                                    is_method: false,
                                });
                                scope.push(name);
                                if let Some(body) = inner.child_by_field_name("body") {
                                    self.walk_children(body, scope, true);
                                }
                                scope.pop();
                            }
                            _ => {}
                        }
                    }
                }
                return;
            }
            "function_definition" => {
                if let Some(name) = field_text(node, "name", self.source) {
                    let qn = qualify_dot(scope, &name);
                    self.symbols.push(Symbol {
                        qualified_name: qn,
                        line_start: (node.start_position().row as u32) + 1,
                        line_end: (node.end_position().row as u32) + 1,
                        text: self.source[node.start_byte()..node.end_byte()].to_string(),
                        kind_tag: "fn",
                        is_method: in_class,
                    });
                }
                // Don't recurse — nested functions handled but currently we
                // emit only top-level + class-body fns. If you later want
                // nested functions, recurse here passing in_class=false.
                return;
            }
            "class_definition" => {
                if let Some(name) = field_text(node, "name", self.source) {
                    let qn = qualify_dot(scope, &name);
                    self.symbols.push(Symbol {
                        qualified_name: qn,
                        line_start: (node.start_position().row as u32) + 1,
                        line_end: (node.end_position().row as u32) + 1,
                        text: self.source[node.start_byte()..node.end_byte()].to_string(),
                        kind_tag: "class",
                        is_method: false,
                    });
                    scope.push(name);
                    if let Some(body) = node.child_by_field_name("body") {
                        self.walk_children(body, scope, true);
                    }
                    scope.pop();
                }
                return;
            }
            "import_statement" => {
                self.collect_imports_simple(node);
                return;
            }
            "import_from_statement" => {
                self.collect_imports_from(node);
                return;
            }
            _ => {}
        }
        self.walk_children(node, scope, in_class);
    }

    fn walk_children(&mut self, node: Node, scope: &mut Vec<String>, in_class: bool) {
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            self.walk(child, scope, in_class);
        }
    }

    fn collect_imports_simple(&mut self, node: Node) {
        // `import x`, `import x.y`, `import x as y` (one or more, comma-sep).
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            match child.kind() {
                "dotted_name" => {
                    self.add_import(node_text(child, self.source).trim().to_string());
                }
                "aliased_import" => {
                    if let Some(name) = child.child_by_field_name("name") {
                        self.add_import(node_text(name, self.source).trim().to_string());
                    }
                }
                _ => {}
            }
        }
    }

    fn collect_imports_from(&mut self, node: Node) {
        // `from x import a, b`, `from .x import y`, `from x import *`.
        // Note: tree-sitter-python uses `module_name` field for the source;
        // imported items are unfielded children of kind `dotted_name`
        // (or `aliased_import`, or `wildcard_import`). We skip the
        // module_name node by remembering its byte offset.
        let module_node = node.child_by_field_name("module_name");
        let module_text = module_node
            .map(|n| node_text(n, self.source).trim().to_string())
            .unwrap_or_default();
        let module_start = module_node.map(|n| n.start_byte());

        let combine = |item: &str| -> String {
            if module_text.is_empty() {
                item.to_string()
            } else {
                format!("{module_text}.{item}")
            }
        };

        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            if Some(child.start_byte()) == module_start {
                continue;
            }
            match child.kind() {
                "dotted_name" => {
                    let item = node_text(child, self.source).trim();
                    self.add_import(combine(item));
                }
                "aliased_import" => {
                    if let Some(name) = child.child_by_field_name("name") {
                        let item = node_text(name, self.source).trim();
                        self.add_import(combine(item));
                    }
                }
                "wildcard_import" => {
                    // skip — no definite target.
                }
                _ => {}
            }
        }
    }

    fn add_import(&mut self, path: String) {
        let raw = path.trim();
        if raw.is_empty() {
            return;
        }
        let prefixed = format!("python:{raw}");
        if !self.imports.iter().any(|p| p == &prefixed) {
            self.imports.push(prefixed);
        }
    }
}

fn qualify_dot(scope: &[String], name: &str) -> String {
    if scope.is_empty() {
        return name.to_string();
    }
    let mut parts: Vec<String> = scope.to_vec();
    parts.push(name.to_string());
    parts.join(".")
}
