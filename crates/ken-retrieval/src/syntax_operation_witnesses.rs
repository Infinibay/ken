//! Observe the frozen Java/JavaScript/TypeScript body relations on catalog bytes.
use crate::{
    EntityKey,
    source_catalog::SourceCatalog,
    source_snapshot::{SourceResult, invalid},
};
use ken_syntax::{GrammarCatalog, Language, SyntaxNode, SyntaxTree};
use ken_text::unicode::whitespace;
use std::{
    cmp::Reverse,
    collections::{BTreeSet, HashMap},
    path::Path,
    sync::Arc,
};
struct FileSyntax {
    source: String,
    tree: SyntaxTree,
}
pub struct SyntaxOperationWitnesses {
    catalog: Arc<SourceCatalog>,
    grammars: Arc<GrammarCatalog>,
    files: HashMap<String, FileSyntax>,
    owners: HashMap<EntityKey, BTreeSet<String>>,
}
fn language(path: &str) -> Option<Language> {
    match Path::new(path).extension()?.to_str()? {
        "java" => Some(Language::Java),
        "js" | "mjs" | "cjs" => Some(Language::JavaScript),
        "ts" | "tsx" => Some(Language::TypeScript),
        _ => None,
    }
}
impl SyntaxOperationWitnesses {
    pub fn new(catalog: Arc<SourceCatalog>, grammars: Arc<GrammarCatalog>) -> Self {
        Self {
            catalog,
            grammars,
            files: HashMap::new(),
            owners: HashMap::new(),
        }
    }
    pub fn supports(path: &str) -> bool {
        language(path).is_some()
    }
    pub fn for_owner(&mut self, key: &EntityKey) -> SourceResult<BTreeSet<String>> {
        self.catalog.passages(key)?;
        let language=language(&key.path).ok_or_else(||invalid("syntax witness backend requires Java/JavaScript/TypeScript; Python AST is separate"))?;
        if let Some(value) = self.owners.get(key) {
            return Ok(value.clone());
        }
        if !self.files.contains_key(&key.path) {
            let source = self.catalog.snapshots()[&key.path].lines().join("\n");
            let tree = self
                .grammars
                .syntax(language, source.as_bytes(), &key.path)
                .map_err(|e| invalid(e.to_string()))?;
            self.files
                .insert(key.path.clone(), FileSyntax { source, tree });
        }
        let result = observe(&self.files[&key.path], self.catalog.extent(key)?)?;
        self.owners.insert(key.clone(), result.clone());
        Ok(result)
    }
}
// This is the original structural frontend's closed callable-kind contract.
fn callable(kind: &str) -> bool {
    matches!(
        kind,
        "abstract_method_signature"
            | "function_definition"
            | "function_declaration"
            | "method_definition"
            | "method_declaration"
            | "constructor_declaration"
            | "function_item"
            | "function_signature_item"
            | "method_signature"
            | "method_elem"
            | "closure_expression"
            | "generator_function_declaration"
            | "generator_function"
            | "arrow_function"
            | "lambda"
            | "local_function_statement"
            | "func_literal"
            | "function_expression"
            | "lambda_expression"
            | "method"
            | "singleton_method"
    )
}
fn unwrap(mut node: SyntaxNode<'_>) -> SyntaxNode<'_> {
    while node.kind() == "parenthesized_expression" {
        let children = node.named_children();
        if children.len() != 1 {
            break;
        }
        node = children[0];
    }
    node
}
fn raw_target(file: &FileSyntax, node: SyntaxNode<'_>) -> SourceResult<String> {
    let raw = file
        .source
        .get(node.start_byte()..node.end_byte())
        .ok_or_else(|| invalid("native syntax source span is invalid"))?;
    Ok(raw.chars().filter(|c| !whitespace(*c)).collect())
}
fn refresh(file: &FileSyntax, node: SyntaxNode<'_>) -> SourceResult<bool> {
    let Some(value) = node.named_children().first().copied().map(unwrap) else {
        return Ok(false);
    };
    if value.kind() != "binary_expression" || !value.children().iter().any(|n| n.kind() == "||") {
        return Ok(false);
    }
    let Some(left) = value.field("left").map(unwrap) else {
        return Ok(false);
    };
    let Some(right) = value.field("right").map(unwrap) else {
        return Ok(false);
    };
    if right.kind() != "assignment_expression" {
        return Ok(false);
    }
    let Some(target) = right.field("left").map(unwrap) else {
        return Ok(false);
    };
    let Some(assigned) = right.field("right").map(unwrap) else {
        return Ok(false);
    };
    Ok(
        matches!(assigned.kind(), "call_expression" | "method_invocation")
            && raw_target(file, left)? == raw_target(file, target)?,
    )
}
fn observe(file: &FileSyntax, [start, end]: [usize; 2]) -> SourceResult<BTreeSet<String>> {
    let mut selected = None;
    let mut pending = vec![file.tree.root()];
    while let Some(node) = pending.pop() {
        let a = node.start_point()[0] + 1;
        let b = node.end_point()[0] + 1;
        if b < start || a > end {
            continue;
        }
        if callable(node.kind()) && start <= a && a <= b && b <= end {
            let candidate = (node.start_byte(), Reverse(node.end_byte()));
            if selected.as_ref().is_none_or(|(best, _)| candidate < *best) {
                selected = Some((candidate, node));
            }
        }
        pending.extend(node.named_children());
    }
    let mut result = BTreeSet::new();
    let Some((_, root)) = selected else {
        return Ok(result);
    };
    if root.end_point()[0] + 1 != end {
        return Ok(result);
    }
    let mut pending = root.field("body").into_iter().collect::<Vec<_>>();
    while let Some(node) = pending.pop() {
        if callable(node.kind()) {
            continue;
        }
        if matches!(
            node.kind(),
            "call_expression"
                | "method_invocation"
                | "new_expression"
                | "object_creation_expression"
                | "explicit_constructor_invocation"
        ) {
            result.insert("invocation".into());
        }
        if node.kind() == "return_statement" && refresh(file, node)? {
            result.insert("returned_flag_refresh".into());
        }
        pending.extend(node.named_children());
    }
    Ok(result)
}
