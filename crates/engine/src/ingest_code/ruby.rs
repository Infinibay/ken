//! Ruby walker. Symbol kinds: `method`, `singleton_method`, `class`,
//! `module`, `singleton_class`. `module` and `class` push into the scope so
//! `Foo::Bar.method` mirrors how Ruby code reads (using `::` for
//! module/class scoping and `.` for method calls).
//!
//! Imports are emitted from `call` nodes whose receiver is a `require`,
//! `require_relative`, or `load` identifier with a string-literal argument
//! — Ruby's "import" is a regular method call, so there is no dedicated
//! grammar node. `require_relative` paths get the `ruby-rel:` namespace,
//! `require`/`load` get the `ruby:` namespace.

use tree_sitter::{Node, Parser};

use super::{node_text, recompute_line_start, Extracted, Symbol};
use crate::ingest::IngestError;

pub(super) fn extract(source: &str) -> crate::ingest::IngestResult<Extracted> {
    let mut parser = Parser::new();
    let language: tree_sitter::Language = tree_sitter_ruby::LANGUAGE.into();
    parser
        .set_language(&language)
        .map_err(|e| IngestError::Unsupported(format!("set ruby language: {e}")))?;
    let tree = parser
        .parse(source.as_bytes(), None)
        .ok_or_else(|| IngestError::Decode("ruby parse returned None".into()))?;
    let mut walker = RubyWalker { source, symbols: Vec::new(), imports: Vec::new() };
    walker.walk(tree.root_node(), &mut Vec::new());
    Ok(Extracted { symbols: walker.symbols, imports: walker.imports })
}

struct RubyWalker<'a> {
    source: &'a str,
    symbols: Vec<Symbol>,
    imports: Vec<String>,
}

impl<'a> RubyWalker<'a> {
    fn walk(&mut self, node: Node, scope: &mut Vec<String>) {
        let kind = node.kind();
        match kind {
            "class" | "module" => {
                if let Some(name) = scope_name(node, self.source) {
                    let tag = if kind == "class" { "class" } else { "module" };
                    self.emit(node, scope, &name, tag, false, "::");
                    scope.push(name);
                    self.walk_children(node, scope);
                    scope.pop();
                    return;
                }
            }
            "method" => {
                if let Some(name) = method_name(node, self.source) {
                    self.emit(node, scope, &name, "fn", !scope.is_empty(), ".");
                    return;
                }
            }
            "singleton_method" => {
                if let Some(name) = method_name(node, self.source) {
                    let qn = format!("self.{name}");
                    self.emit(node, scope, &qn, "fn", false, ".");
                    return;
                }
            }
            "call" => {
                self.maybe_collect_require(node);
                // Don't return — there could be nested requires inside conditional bodies.
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
        sep: &str,
    ) {
        // Members of a class/module are joined to their parent with `sep`
        // (`.` for methods, `::` for nested modules), while the parent
        // chain itself is always joined with `::` (Ruby's scoping syntax).
        let qn = if scope.is_empty() {
            name.to_string()
        } else {
            let parent = scope.join("::");
            format!("{parent}{sep}{name}")
        };
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

    fn maybe_collect_require(&mut self, node: Node) {
        // `call` shape we want: method=identifier (`require`/`require_relative`/`load`),
        // arguments=argument_list with a single string child.
        let method = node.child_by_field_name("method").or_else(|| node.child_by_field_name("name"));
        let Some(method) = method else { return };
        let name = node_text(method, self.source).trim();
        let prefix = match name {
            "require" | "load" | "require_dependency" | "autoload" => "ruby:",
            "require_relative" => "ruby-rel:",
            _ => return,
        };
        let Some(args) = node.child_by_field_name("arguments") else { return };
        let mut cursor = args.walk();
        for child in args.children(&mut cursor) {
            if matches!(child.kind(), "string" | "string_literal") {
                if let Some(text) = string_literal_text(child, self.source) {
                    if !text.is_empty() {
                        let p = format!("{prefix}{text}");
                        if !self.imports.iter().any(|x| x == &p) {
                            self.imports.push(p);
                        }
                    }
                }
            }
        }
    }
}

fn scope_name(node: Node, source: &str) -> Option<String> {
    node.child_by_field_name("name")
        .map(|n| node_text(n, source).trim().to_string())
        .filter(|s| !s.is_empty())
}

fn method_name(node: Node, source: &str) -> Option<String> {
    node.child_by_field_name("name")
        .map(|n| node_text(n, source).trim().to_string())
        .filter(|s| !s.is_empty())
}

fn string_literal_text(node: Node, source: &str) -> Option<String> {
    // tree-sitter-ruby `string` node has children: opening quote, string_content, closing quote.
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "string_content" {
            return Some(node_text(child, source).to_string());
        }
    }
    // Fallback: strip outer quotes.
    let raw = node_text(node, source).trim();
    Some(raw.trim_matches('"').trim_matches('\'').to_string())
}

/// Walk previous siblings consuming consecutive `# ...` line comments. Ruby
/// has no formal docstring syntax — convention is consecutive `#` lines.
fn expand_with_doc_comments(node: Node, source: &str) -> (usize, usize) {
    let mut start = node.start_byte();
    let end = node.end_byte();
    let mut cursor = node;
    while let Some(prev) = cursor.prev_sibling() {
        if prev.kind() == "comment" {
            let text = node_text(prev, source);
            if text.starts_with('#') {
                start = prev.start_byte();
                cursor = prev;
                continue;
            }
        }
        break;
    }
    (start, end)
}
