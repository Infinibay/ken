//! Source-operation producer stage. Full declaration and semantic projection are separate.
mod frontend;
mod operations;
mod ownership;
mod source;
mod vocabulary;
use crate::{GrammarCatalog, Language, ParseError};
use ken_program::{Attributes, ProgramError, StructuralIr};
use serde_json::{Value, value::to_raw_value};

#[derive(Debug, thiserror::Error)]
pub enum LoweringError {
    #[error(transparent)]
    Parse(#[from] ParseError),
    #[error(transparent)]
    Program(#[from] ProgramError),
    #[error("structural frontend unavailable for {0}")]
    UnsupportedLanguage(&'static str),
}
fn attributes(value: Value) -> Attributes {
    value
        .as_object()
        .expect("structural attributes object")
        .iter()
        .map(|(k, v)| {
            (
                k.clone(),
                to_raw_value(v).expect("JSON structural attribute"),
            )
        })
        .collect()
}
/// Parse named source operations with lexical ownership, operators and execution.
/// Owner records carry source identity only. `syntax` is the sole completeness
/// capability; this stage does not advertise declarations, semantic calls or types.
pub fn lower_operations(
    catalog: &GrammarCatalog,
    language: Language,
    source: &[u8],
    path: &str,
) -> Result<StructuralIr, LoweringError> {
    frontend::syntax_view(catalog, language, source, path)
}
/// Lower complete source-local declarations, bindings, expressions and semantic facts.
/// Project-wide import/type/call resolution and interprocedural analysis are separate.
pub fn lower_source(
    catalog: &GrammarCatalog,
    language: Language,
    source: &[u8],
    path: &str,
) -> Result<StructuralIr, LoweringError> {
    frontend::lower(catalog, language, source, path)
}
fn admit(language: Language) -> Result<(), LoweringError> {
    if matches!(
        language,
        Language::Python
            | Language::JavaScript
            | Language::TypeScript
            | Language::Java
            | Language::CSharp
            | Language::Cpp
            | Language::Go
            | Language::Rust
            | Language::Ruby
    ) {
        Ok(())
    } else {
        Err(LoweringError::UnsupportedLanguage(language.as_str()))
    }
}

/// Classification of raw syntax, without declaration or source-operation lowering.
pub fn syntax_classification(native: &str) -> (String, String) {
    if let Some((kind, category)) = ken_program::raw_syntax_kind(native) {
        return (kind.into(), category.into());
    }
    let v = vocabulary::vocabulary();
    let result = if v.types.contains(native) {
        ("type_declaration", "declaration")
    } else if v.functions.contains(native) {
        ("callable", "declaration")
    } else if v.calls.contains(native) {
        ("call", "expression")
    } else if v.assignments.contains(native) {
        ("assignment", "expression")
    } else if v.members.contains(native) {
        ("member", "expression")
    } else if matches!(
        native,
        "binary_expression" | "binary_operator" | "boolean_operator" | "comparison_operator"
    ) {
        ("binary", "expression")
    } else if matches!(
        native,
        "unary_expression" | "unary_operator" | "not_operator"
    ) {
        ("unary", "expression")
    } else {
        ("opaque", "opaque")
    };
    (result.0.into(), result.1.into())
}
