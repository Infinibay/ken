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
