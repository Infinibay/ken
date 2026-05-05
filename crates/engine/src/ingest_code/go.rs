//! Go walker. Symbol kinds: `function_declaration`, `method_declaration`,
//! `type_declaration` (struct/interface/alias). Imports come from
//! `import_declaration` (`import "x"` and `import ( "a"; "b" )`).
//!
//! Methods get a qualified name `Receiver.Method` mirroring Go's call syntax.
//! Pointer receivers (`*User`) collapse to `User` for the qualified name —
//! callers don't write `(*User).Method` in practice.

use tree_sitter::{Node, Parser};

use super::{field_text, node_text, recompute_line_start, Extracted, Symbol};
use crate::ingest::IngestError;

pub(super) fn extract(source: &str) -> crate::ingest::IngestResult<Extracted> {
    let mut parser = Parser::new();
    let language: tree_sitter::Language = tree_sitter_go::LANGUAGE.into();
    parser
        .set_language(&language)
        .map_err(|e| IngestError::Unsupported(format!("set go language: {e}")))?;
    let tree = parser
        .parse(source.as_bytes(), None)
        .ok_or_else(|| IngestError::Decode("go parse returned None".into()))?;
    let mut walker = GoWalker { source, symbols: Vec::new(), imports: Vec::new() };
    walker.walk(tree.root_node());
    Ok(Extracted { symbols: walker.symbols, imports: walker.imports })
}

struct GoWalker<'a> {
    source: &'a str,
    symbols: Vec<Symbol>,
    imports: Vec<String>,
}

impl<'a> GoWalker<'a> {
    fn walk(&mut self, node: Node) {
        let kind = node.kind();
        match kind {
            "function_declaration" => {
                if let Some(name) = field_text(node, "name", self.source) {
                    let (start, end) = expand_with_doc_comments(node, self.source);
                    let line_start = recompute_line_start(self.source, start);
                    let line_end = (node.end_position().row as u32) + 1;
                    self.symbols.push(Symbol {
                        qualified_name: name,
                        line_start,
                        line_end,
                        text: self.source[start..end].to_string(),
                        kind_tag: "fn",
                        is_method: false,
                    });
                }
                return;
            }
            "method_declaration" => {
                if let Some(name) = field_text(node, "name", self.source) {
                    let receiver = method_receiver_type(node, self.source);
                    let qn = match receiver {
                        Some(r) => format!("{r}.{name}"),
                        None => name,
                    };
                    let (start, end) = expand_with_doc_comments(node, self.source);
                    let line_start = recompute_line_start(self.source, start);
                    let line_end = (node.end_position().row as u32) + 1;
                    self.symbols.push(Symbol {
                        qualified_name: qn,
                        line_start,
                        line_end,
                        text: self.source[start..end].to_string(),
                        kind_tag: "fn",
                        is_method: true,
                    });
                }
                return;
            }
            "type_declaration" => {
                self.handle_type_declaration(node);
                return;
            }
            "import_declaration" => {
                self.handle_import_declaration(node);
                return;
            }
            _ => {}
        }
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            self.walk(child);
        }
    }

    fn handle_type_declaration(&mut self, node: Node) {
        // `type Foo struct {...}`, `type Foo interface {...}`, `type Foo = Bar`,
        // or grouped: `type ( Foo struct{...}; Bar interface{...} )`.
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            match child.kind() {
                "type_spec" | "type_alias" => {
                    if let Some(name) = field_text(child, "name", self.source) {
                        let tag = if let Some(ty) = child.child_by_field_name("type") {
                            match ty.kind() {
                                "struct_type" => "struct",
                                "interface_type" => "interface",
                                _ => "type",
                            }
                        } else {
                            "type"
                        };
                        // For grouped `type (...)` we still emit one chunk per spec
                        // but expand doc comments only at the outer node level for
                        // single-line decls. Keeping per-spec slice avoids merging
                        // unrelated specs into one chunk.
                        let (start, end) = expand_with_doc_comments(child, self.source);
                        let outer_start = if node.named_child_count() == 1 {
                            // Only one spec — also pull `type` keyword from outer.
                            let (os, _) = expand_with_doc_comments(node, self.source);
                            os.min(start)
                        } else {
                            start
                        };
                        let line_start = recompute_line_start(self.source, outer_start);
                        let line_end = (child.end_position().row as u32) + 1;
                        self.symbols.push(Symbol {
                            qualified_name: name,
                            line_start,
                            line_end,
                            text: self.source[outer_start..end].to_string(),
                            kind_tag: tag,
                            is_method: false,
                        });
                    }
                }
                _ => {}
            }
        }
    }

    fn handle_import_declaration(&mut self, node: Node) {
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            match child.kind() {
                "import_spec" => self.collect_import_spec(child),
                "import_spec_list" => {
                    let mut inner = child.walk();
                    for spec in child.children(&mut inner) {
                        if spec.kind() == "import_spec" {
                            self.collect_import_spec(spec);
                        }
                    }
                }
                _ => {}
            }
        }
    }

    fn collect_import_spec(&mut self, spec: Node) {
        // import_spec has `path` field of kind interpreted_string_literal.
        let path_node = spec.child_by_field_name("path");
        if let Some(p) = path_node {
            let raw = node_text(p, self.source);
            let unquoted = strip_string_literal(raw);
            if unquoted.is_empty() {
                return;
            }
            let prefixed = format!("go:{unquoted}");
            if !self.imports.iter().any(|p| p == &prefixed) {
                self.imports.push(prefixed);
            }
        }
    }
}

fn method_receiver_type(node: Node, source: &str) -> Option<String> {
    let receiver = node.child_by_field_name("receiver")?;
    // receiver is a `parameter_list` containing a `parameter_declaration`
    // whose `type` field gives the receiver type (possibly a `pointer_type`).
    let mut cursor = receiver.walk();
    for param in receiver.children(&mut cursor) {
        if param.kind() == "parameter_declaration" {
            if let Some(ty) = param.child_by_field_name("type") {
                return Some(strip_pointer(node_text(ty, source)).trim().to_string());
            }
        }
    }
    None
}

fn strip_pointer(s: &str) -> &str {
    s.trim().strip_prefix('*').unwrap_or(s.trim())
}

fn strip_string_literal(s: &str) -> &str {
    let s = s.trim();
    s.strip_prefix('"')
        .and_then(|x| x.strip_suffix('"'))
        .unwrap_or(s)
        .trim()
}

/// Walk previous siblings, consuming consecutive `//` line comments so the
/// chunk includes the doc-comment block. Stops at the first non-comment.
fn expand_with_doc_comments(node: Node, _source: &str) -> (usize, usize) {
    let mut start = node.start_byte();
    let end = node.end_byte();
    let mut cursor = node;
    while let Some(prev) = cursor.prev_sibling() {
        if prev.kind() == "comment" {
            start = prev.start_byte();
            cursor = prev;
        } else {
            break;
        }
    }
    (start, end)
}
