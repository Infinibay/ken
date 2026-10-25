use ken_retrieval::{
    EntityKey,
    query::SearchRequest,
    symbol_preferences::{apply_symbol_preferences, is_test_case},
    symbol_requirements::requirements,
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{collections::BTreeSet, fs};
#[path = "source_catalog.rs"]
mod source_catalog;
pub use source_catalog::{Physical, ProbeResult, catalog};
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Input {
    pub request: SearchRequest,
    #[serde(default)]
    pub witnesses: Vec<BTreeSet<String>>,
    #[serde(default)]
    pub test_cases: Vec<bool>,
    #[serde(default)]
    pub implementations: Vec<PythonText>,
    #[serde(default)]
    pub order: Vec<usize>,
}
pub fn observe(kind: &str, input: &Input) -> ProbeResult<Value> {
    let required = requirements(&input.request);
    let mut result = serde_json::to_value(&required)?;
    match kind {
        "requirements" => {}
        "preferences" => {
            result["order"] = json!(apply_symbol_preferences(
                &required,
                &input.witnesses,
                &input.test_cases,
                &input.implementations,
                &input.order
            )?);
        }
        _ => return Err("unknown symbol preference frame".into()),
    }
    Ok(result)
}
pub fn classify(input: Physical) -> ProbeResult<Value> {
    let (directory, catalog) = catalog(input)?;
    // Deliberately mutate disk: all classifications must remain bound to the snapshot.
    for path in catalog.snapshots().keys() {
        fs::write(
            directory.path().join(path),
            b"changed after catalog creation\n",
        )?;
    }
    let mut output = Vec::new();
    for (key, _) in catalog.owners() {
        output.push(json!({"key":key,"test_case":is_test_case(key,&catalog)?}));
    }
    let unknown = EntityKey {
        path: "missing.py".into(),
        kind: "function".into(),
        qualname: Some("test_missing".into()),
        owner: None,
        definition_ordinal: 0,
    };
    output.push(json!({"key":unknown,"test_case":is_test_case(&unknown,&catalog)?}));
    Ok(json!(output))
}
