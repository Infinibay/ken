use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_retrieval::{
    EntityKey, Passage,
    query::SearchRequest,
    source_catalog::SourceCatalog,
    source_snapshot::SourceAuthority,
    symbol_preferences::{apply_symbol_preferences, is_test_case},
    symbol_requirements::requirements,
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Component,
    sync::Arc,
};
pub type ProbeResult<T> = std::result::Result<T, Box<dyn std::error::Error>>;
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
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Physical {
    pub files: BTreeMap<String, Vec<u8>>,
    pub owners: Vec<Owner>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Owner {
    pub key: EntityKey,
    pub passages: Vec<Passage>,
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
pub fn catalog(input: Physical) -> ProbeResult<(tempfile::TempDir, SourceCatalog)> {
    let directory = tempfile::tempdir()?;
    for (name, bytes) in input.files {
        let relative = std::path::Path::new(&name);
        if !relative
            .components()
            .all(|part| matches!(part, Component::Normal(_)))
            || relative.as_os_str().is_empty()
        {
            return Err("relative source paths required".into());
        }
        let path = directory.path().join(relative);
        fs::create_dir_all(path.parent().ok_or("source parent required")?)?;
        fs::write(path, bytes)?;
    }
    let context = DiscoveryContext {
        cwd: directory.path().into(),
        forced_root: None,
        home: None,
    };
    let paths = ProjectPaths::at(directory.path(), &context)?;
    let source = Arc::new(SourceAuthority::new(&paths)?);
    let catalog = SourceCatalog::new(
        source,
        input
            .owners
            .into_iter()
            .map(|o| (o.key, o.passages))
            .collect(),
    )?;
    Ok((directory, catalog))
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
