//! C / C++ walker. Shared because the grammars share most node kinds —
//! C++ adds `class_specifier`, `namespace_definition`, and template wrappers.
//!
//! Symbols emitted: `function_definition`, `struct_specifier`,
//! `union_specifier`, `enum_specifier`, plus C++ `class_specifier`,
//! `namespace_definition` and `template_declaration` (we recurse into the
//! template body to emit the wrapped declaration).
//!
//! Imports: `preproc_include` (`#include <stdio.h>` / `#include "foo.h"`).
//! Angle-bracket headers → `c-system:<name>`, quoted headers → `c:<name>` so
//! the namespace tells you whether the path is system-managed or local.
//! C++ namespaces push into the scope so members read as `ns::Class::method`.

use tree_sitter::{Node, Parser};

use super::{node_text, recompute_line_start, Extracted, Symbol};
use crate::ingest::IngestError;

pub(super) fn extract(source: &str, cpp: bool) -> crate::ingest::IngestResult<Extracted> {
    let mut parser = Parser::new();
    let language: tree_sitter::Language = if cpp {
        tree_sitter_cpp::LANGUAGE.into()
    } else {
        tree_sitter_c::LANGUAGE.into()
    };
    parser
        .set_language(&language)
        .map_err(|e| IngestError::Unsupported(format!("set c/c++ language: {e}")))?;
    let tree = parser
        .parse(source.as_bytes(), None)
        .ok_or_else(|| IngestError::Decode("c/c++ parse returned None".into()))?;
    let mut walker = CWalker { source, symbols: Vec::new(), imports: Vec::new(), cpp };
    walker.walk(tree.root_node(), &mut Vec::new());
    Ok(Extracted { symbols: walker.symbols, imports: walker.imports })
}

struct CWalker<'a> {
    source: &'a str,
    symbols: Vec<Symbol>,
    imports: Vec<String>,
    cpp: bool,
}

impl<'a> CWalker<'a> {
    fn walk(&mut self, node: Node, scope: &mut Vec<String>) {
        let kind = node.kind();
        match kind {
            "function_definition" => {
                if let Some(name) = function_name(node, self.source) {
                    self.emit(node, scope, &name, "fn", !scope.is_empty());
                }
                return;
            }
            "struct_specifier" | "union_specifier" | "enum_specifier" => {
                let tag = match kind {
                    "struct_specifier" => "struct",
                    "union_specifier" => "union",
                    "enum_specifier" => "enum",
                    _ => "type",
                };
                if let Some(name) = name_of(node, self.source) {
                    // Anonymous structs (no name field) are skipped — they
                    // typically appear inline in a typedef and have no
                    // standalone identity worth indexing.
                    self.emit(node, scope, &name, tag, false);
                    if self.cpp {
                        scope.push(name);
                        self.walk_children(node, scope);
                        scope.pop();
                        return;
                    }
                }
            }
            "class_specifier" if self.cpp => {
                if let Some(name) = name_of(node, self.source) {
                    self.emit(node, scope, &name, "class", false);
                    scope.push(name);
                    self.walk_children(node, scope);
                    scope.pop();
                    return;
                }
            }
            "namespace_definition" if self.cpp => {
                let name = node
                    .child_by_field_name("name")
                    .map(|n| node_text(n, self.source).trim().to_string())
                    .unwrap_or_else(|| "<anon>".to_string());
                scope.push(name);
                self.walk_children(node, scope);
                scope.pop();
                return;
            }
            "template_declaration" if self.cpp => {
                // Recurse so we still pick up the wrapped function/class.
                self.walk_children(node, scope);
                return;
            }
            "preproc_include" => {
                self.collect_include(node);
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

    fn emit(
        &mut self,
        node: Node,
        scope: &mut Vec<String>,
        name: &str,
        kind_tag: &'static str,
        is_method: bool,
    ) {
        let qn = qualify_cpp(scope, name);
        let (start, end) = expand_with_doc_comments(node, self.source);
        let line_start = recompute_line_start(self.source, start);
        let line_end = (node.end_position().row as u32) + 1;
        self.symbols.push(Symbol {
            qualified_name: qn,
            line_start,
            line_end,
            text: self.source[start..end].to_string(),
            kind_tag,
            is_method,
        });
    }

    fn collect_include(&mut self, node: Node) {
        // Children: `#include` token, then path of kind
        // `system_lib_string` (<...>) or `string_literal` ("...").
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            match child.kind() {
                "system_lib_string" => {
                    let raw = node_text(child, self.source).trim();
                    let inner = raw.trim_start_matches('<').trim_end_matches('>').trim();
                    if !inner.is_empty() {
                        let p = format!("c-system:{inner}");
                        if !self.imports.iter().any(|x| x == &p) {
                            self.imports.push(p);
                        }
                    }
                }
                "string_literal" => {
                    let raw = node_text(child, self.source).trim();
                    let inner = raw.trim_matches('"').trim();
                    if !inner.is_empty() {
                        let p = format!("c:{inner}");
                        if !self.imports.iter().any(|x| x == &p) {
                            self.imports.push(p);
                        }
                    }
                }
                _ => {}
            }
        }
    }
}

/// Recursively descends a `function_definition`'s `declarator` field to find
/// the underlying identifier. Pointer/reference/parens declarators wrap the
/// real name in C/C++ — `int *foo(...)` parses with a `pointer_declarator`
/// outside `function_declarator`. The tree-sitter grammar exposes `declarator`
/// as a chained field, so we walk down until we hit something atomic.
fn function_name(node: Node, source: &str) -> Option<String> {
    let mut cur = node.child_by_field_name("declarator")?;
    loop {
        match cur.kind() {
            "function_declarator" => {
                cur = cur.child_by_field_name("declarator")?;
            }
            "pointer_declarator"
            | "reference_declarator"
            | "parenthesized_declarator"
            | "abstract_pointer_declarator" => {
                // Fall through to inner declarator.
                if let Some(inner) = cur.child_by_field_name("declarator") {
                    cur = inner;
                } else {
                    return None;
                }
            }
            "identifier" | "field_identifier" | "type_identifier" => {
                return Some(node_text(cur, source).trim().to_string());
            }
            "qualified_identifier" | "destructor_name" | "operator_name" => {
                return Some(node_text(cur, source).trim().to_string());
            }
            _ => return Some(node_text(cur, source).trim().to_string()),
        }
    }
}

fn name_of(node: Node, source: &str) -> Option<String> {
    node.child_by_field_name("name")
        .map(|n| node_text(n, source).trim().to_string())
        .filter(|s| !s.is_empty())
}

fn qualify_cpp(scope: &[String], name: &str) -> String {
    if scope.is_empty() {
        return name.to_string();
    }
    let mut parts: Vec<String> = scope.to_vec();
    parts.push(name.to_string());
    parts.join("::")
}

/// Walk previous siblings consuming `///` line comments and `/** */` block
/// comments (Doxygen / generic doc style). Plain `//` and `/* */` comments
/// are skipped to avoid pulling in random commentary.
fn expand_with_doc_comments(node: Node, source: &str) -> (usize, usize) {
    let mut start = node.start_byte();
    let end = node.end_byte();
    let mut cursor = node;
    while let Some(prev) = cursor.prev_sibling() {
        if prev.kind() == "comment" {
            let text = node_text(prev, source);
            if text.starts_with("///") || text.starts_with("/**") || text.starts_with("//!") {
                start = prev.start_byte();
                cursor = prev;
                continue;
            }
        }
        break;
    }
    (start, end)
}
