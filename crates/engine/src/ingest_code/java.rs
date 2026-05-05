//! Java walker. Symbol kinds: `class_declaration`, `interface_declaration`,
//! `enum_declaration`, `record_declaration`, plus `method_declaration` and
//! `constructor_declaration` inside class bodies. Methods are qualified
//! against their containing class — `User.validate`. Nested types push
//! into the scope so `Outer.Inner.method` works.
//!
//! Imports come from `import_declaration`. We strip the trailing `;` and
//! `static`/`*` modifiers from the path. Wildcard `import foo.bar.*;` is
//! dropped (no definite target). The `package` declaration is captured as
//! a synthetic `java:<pkg>` entry — it informs cross-file resolution.

use tree_sitter::{Node, Parser};

use super::{field_text, node_text, recompute_line_start, Extracted, Symbol};
use crate::ingest::IngestError;

pub(super) fn extract(source: &str) -> crate::ingest::IngestResult<Extracted> {
    let mut parser = Parser::new();
    let language: tree_sitter::Language = tree_sitter_java::LANGUAGE.into();
    parser
        .set_language(&language)
        .map_err(|e| IngestError::Unsupported(format!("set java language: {e}")))?;
    let tree = parser
        .parse(source.as_bytes(), None)
        .ok_or_else(|| IngestError::Decode("java parse returned None".into()))?;
    let mut walker = JavaWalker { source, symbols: Vec::new(), imports: Vec::new() };
    walker.walk(tree.root_node(), &mut Vec::new());
    Ok(Extracted { symbols: walker.symbols, imports: walker.imports })
}

struct JavaWalker<'a> {
    source: &'a str,
    symbols: Vec<Symbol>,
    imports: Vec<String>,
}

impl<'a> JavaWalker<'a> {
    fn walk(&mut self, node: Node, scope: &mut Vec<String>) {
        let kind = node.kind();
        match kind {
            "class_declaration"
            | "interface_declaration"
            | "enum_declaration"
            | "record_declaration"
            | "annotation_type_declaration" => {
                if let Some(name) = field_text(node, "name", self.source) {
                    let tag = match kind {
                        "class_declaration" => "class",
                        "interface_declaration" => "interface",
                        "enum_declaration" => "enum",
                        "record_declaration" => "record",
                        "annotation_type_declaration" => "annotation",
                        _ => "type",
                    };
                    self.emit(node, scope, &name, tag, false);
                    scope.push(name);
                    if let Some(body) = node.child_by_field_name("body") {
                        self.walk_children(body, scope);
                    }
                    scope.pop();
                    return;
                }
            }
            "method_declaration" | "constructor_declaration" => {
                let name = field_text(node, "name", self.source).unwrap_or_else(|| "<anon>".into());
                self.emit(node, scope, &name, "fn", !scope.is_empty());
                return;
            }
            "import_declaration" => {
                self.collect_import(node);
                return;
            }
            "package_declaration" => {
                self.collect_package(node);
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
        let qn = qualify_dot(scope, name);
        let (start, end) = expand_with_javadoc_and_annotations(node, self.source);
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

    fn collect_import(&mut self, node: Node) {
        let mut cursor = node.walk();
        // import_declaration → 'import' [static] scoped_identifier|asterisk ;
        let mut buf = String::new();
        let mut hit_wildcard = false;
        for child in node.children(&mut cursor) {
            match child.kind() {
                "scoped_identifier" | "identifier" => {
                    if !buf.is_empty() {
                        return; // unexpected — bail safely
                    }
                    buf.push_str(node_text(child, self.source).trim());
                }
                "asterisk" => hit_wildcard = true,
                _ => {}
            }
        }
        if buf.is_empty() || hit_wildcard {
            return;
        }
        let prefixed = format!("java:{buf}");
        if !self.imports.iter().any(|p| p == &prefixed) {
            self.imports.push(prefixed);
        }
    }

    fn collect_package(&mut self, node: Node) {
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            if matches!(child.kind(), "scoped_identifier" | "identifier") {
                let pkg = node_text(child, self.source).trim().to_string();
                if !pkg.is_empty() {
                    let prefixed = format!("java:{pkg}");
                    if !self.imports.iter().any(|p| p == &prefixed) {
                        self.imports.push(prefixed);
                    }
                }
                return;
            }
        }
    }
}

/// Walk previous siblings, consuming consecutive Javadoc `/** ... */`
/// comments and any preceding `marker_annotation` / `annotation` nodes.
fn expand_with_javadoc_and_annotations(node: Node, source: &str) -> (usize, usize) {
    let mut start = node.start_byte();
    let end = node.end_byte();
    // Annotations on declarations are typically children of the declaration
    // (in tree-sitter-java they appear as `modifiers` field). So we mainly
    // need to walk back over Javadoc comments.
    let mut cursor = node;
    while let Some(prev) = cursor.prev_sibling() {
        if prev.kind() == "block_comment" {
            let text = node_text(prev, source);
            if text.starts_with("/**") {
                start = prev.start_byte();
                cursor = prev;
                continue;
            }
        }
        break;
    }
    (start, end)
}

fn qualify_dot(scope: &[String], name: &str) -> String {
    if scope.is_empty() {
        return name.to_string();
    }
    let mut parts: Vec<String> = scope.to_vec();
    parts.push(name.to_string());
    parts.join(".")
}
