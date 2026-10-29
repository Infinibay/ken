//! Source-operation producer stage. Full declaration and semantic projection are separate.
mod operations;
mod ownership;
mod source;
mod vocabulary;
use crate::{GrammarCatalog, Language, ParseError};
use ken_program::{Attributes, IR_VERSION, ProgramError, StructuralIr, control::lexical_execution};
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
    if !matches!(
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
        return Err(LoweringError::UnsupportedLanguage(language.as_str()));
    }
    let tree = catalog.syntax(language, source, path)?;
    let root = tree.root();
    let owners = ownership::Ownership::collect(root, language, source, path);
    let mut ir = StructuralIr {
        path: path.into(),
        language: language.as_str().into(),
        entities: Vec::new(),
        operations: Vec::new(),
        facts: Vec::new(),
        capabilities: ["syntax".into()].into_iter().collect(),
        diagnostics: Vec::new(),
        version: IR_VERSION.into(),
        relations: Default::default(),
        view: "source".into(),
    };
    for (node, role) in source::descendants_with_roles(root) {
        operations::project(&mut ir, node, role, &owners, source, language);
    }
    ir.entities = owners.owner_entities();
    if root.has_error() {
        ir.diagnostics
            .push("parse errors: semantic absence is unknown".into());
    }
    lexical_execution(&mut ir, root.has_error())?;
    Ok(ir)
}
