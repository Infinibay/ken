//! Safe syntax views keep the backing dynamic grammar alive.
use crate::grammar::Grammar;
use std::sync::Arc;

// Drop the raw tree first; only then release its grammar's native library.
pub struct SyntaxTree {
    tree: tree_sitter::Tree,
    _grammar: Arc<Grammar>,
}
#[derive(Clone, Copy)]
pub struct SyntaxNode<'tree> {
    raw: tree_sitter::Node<'tree>,
    owner: &'tree SyntaxTree,
}

#[derive(serde::Serialize)]
pub struct SyntaxRecord(
    String,
    bool,
    bool,
    usize,
    usize,
    [usize; 2],
    [usize; 2],
    Option<usize>,
    Option<String>,
    bool,
);

impl SyntaxTree {
    pub(crate) fn new(tree: tree_sitter::Tree, grammar: Arc<Grammar>) -> Self {
        Self {
            tree,
            _grammar: grammar,
        }
    }
    pub fn root(&self) -> SyntaxNode<'_> {
        SyntaxNode {
            raw: self.tree.root_node(),
            owner: self,
        }
    }
    pub fn snapshot(&self) -> Vec<SyntaxRecord> {
        let mut rows = Vec::new();
        let mut pending = vec![(self.tree.root_node(), None, None)];
        while let Some((node, parent, field)) = pending.pop() {
            let index = rows.len();
            let start = node.start_position();
            let end = node.end_position();
            rows.push(SyntaxRecord(
                node.kind().into(),
                node.is_named(),
                node.is_missing(),
                node.start_byte(),
                node.end_byte(),
                [start.row, start.column],
                [end.row, end.column],
                parent,
                field,
                node.has_error(),
            ));
            for child_index in (0..node.child_count()).rev() {
                if let Some(child) = node.child(child_index) {
                    pending.push((
                        child,
                        Some(index),
                        node.field_name_for_child(child_index as u32)
                            .map(str::to_owned),
                    ));
                }
            }
        }
        rows
    }
}
impl<'tree> SyntaxNode<'tree> {
    fn wrap(self, raw: tree_sitter::Node<'tree>) -> Self {
        Self {
            raw,
            owner: self.owner,
        }
    }
    /// The returned view cannot outlive the tree's grammar module.
    /// ```compile_fail
    /// use ken_syntax::{GrammarCatalog, Language};
    /// fn escaped_kind(catalog: &GrammarCatalog) -> &'static str {
    ///     let tree = catalog.syntax(Language::Cpp, b"", "empty.cpp").unwrap();
    ///     tree.root().kind()
    /// }
    /// ```
    pub fn kind(self) -> &'tree str {
        self.raw.kind()
    }
    pub fn start_byte(self) -> usize {
        self.raw.start_byte()
    }
    pub fn end_byte(self) -> usize {
        self.raw.end_byte()
    }
    pub fn start_point(self) -> [usize; 2] {
        let p = self.raw.start_position();
        [p.row, p.column]
    }
    pub fn end_point(self) -> [usize; 2] {
        let p = self.raw.end_position();
        [p.row, p.column]
    }
    pub fn is_named(self) -> bool {
        self.raw.is_named()
    }
    pub fn is_missing(self) -> bool {
        self.raw.is_missing()
    }
    pub fn has_error(self) -> bool {
        self.raw.has_error()
    }
    pub fn children(self) -> Vec<Self> {
        (0..self.raw.child_count())
            .filter_map(|i| self.raw.child(i))
            .map(|n| self.wrap(n))
            .collect()
    }
    pub fn named_children(self) -> Vec<Self> {
        (0..self.raw.named_child_count())
            .filter_map(|i| self.raw.named_child(i))
            .map(|n| self.wrap(n))
            .collect()
    }
    pub fn field(self, name: &str) -> Option<Self> {
        self.raw.child_by_field_name(name).map(|n| self.wrap(n))
    }
    pub fn parent(self) -> Option<Self> {
        self.raw.parent().map(|n| self.wrap(n))
    }
    pub fn previous_named_sibling(self) -> Option<Self> {
        self.raw.prev_named_sibling().map(|n| self.wrap(n))
    }
    pub fn next_named_sibling(self) -> Option<Self> {
        self.raw.next_named_sibling().map(|node| self.wrap(node))
    }
}
