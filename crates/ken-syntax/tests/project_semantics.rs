//! Complete native bytes→project semantics→AST/store boundary, without Python.
use flate2::read::GzDecoder;
use ken_program::{StructuralIr, normalize_syntax, project::link_project};
use ken_store::structural::StructuralStore;
use ken_syntax::{GrammarCatalog, Language, structural::lower_source};
use serde::Deserialize;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{io::Read, path::PathBuf};
#[derive(Deserialize)]
struct Case {
    name: String,
    source: Option<String>,
    language: Option<Language>,
    path: Option<String>,
    result: Value,
}
fn canonical(mut ir: Value) -> Value {
    // Block-local IDs already carry their stable @block-start identity; production
    // preserves Node.id addresses, which cannot equal across parser processes.
    for (id, e) in ir["entities"].as_object_mut().unwrap() {
        if let Some(raw) = e["attrs"].get("block_scope") {
            assert!(raw.as_u64().is_some_and(|n| n > 0));
            e["attrs"]["block_scope"] =
                format!("block-at:{}", id.rsplit_once('@').unwrap().1).into();
        }
    }
    // ENTITY facts also publish the same attribute; use that same stable subject ID.
    for f in ir["facts"].as_array_mut().unwrap() {
        if f["relation"] == "ENTITY" && f["attrs"].get("block_scope").is_some() {
            assert!(f["attrs"]["block_scope"].as_u64().is_some_and(|n| n > 0));
            f["attrs"]["block_scope"] = format!(
                "block-at:{}",
                f["subject"].as_str().unwrap().rsplit_once('@').unwrap().1
            )
            .into();
        }
    }
    ir["facts"]
        .as_array_mut()
        .unwrap()
        .sort_by_key(Value::to_string);
    ir
}
#[test]
fn new_sources_reach_original_full_project_and_reopen_every_semantic_fact() {
    let bytes =
        include_bytes!("../../ken-program/tests/fixtures/project-semantics-reference.json.gz");
    assert_eq!(bytes.len(), 1007022);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "f50c367a4a8c2391c40a928e1dfcec0dcb3931e35b4bc17b09aa70ca3bda8479"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    #[derive(Deserialize)]
    struct Corpus {
        cases: Vec<Case>,
    }
    let corpus: Corpus = serde_json::from_str(&text).unwrap();
    let catalog = GrammarCatalog::prepared(&PathBuf::from(
        std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
    ))
    .unwrap();
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("project.sqlite");
    let mut store = StructuralStore::open(Some(&path), None).unwrap();
    let mut units = vec![];
    let mut expected = vec![];
    for c in corpus.cases {
        let Some(source) = c.source else {
            continue;
        };
        let unit = lower_source(
            &catalog,
            c.language.unwrap(),
            source.as_bytes(),
            &c.path.unwrap(),
        )
        .unwrap();
        let project = link_project(&[unit]).unwrap();
        assert_eq!(
            canonical(serde_json::to_value(&project).unwrap()),
            canonical(c.result),
            "{}",
            c.name
        );
        normalize_syntax(&project).unwrap().validate().unwrap();
        let key = store
            .put_unit(
                &c.name,
                &project,
                "source-revision",
                "semantic-project/1",
                project.diagnostics.is_empty(),
            )
            .unwrap();
        // Independent projects share the <project> IR path; each is a new
        // revision, rather than two revisions of that path in one snapshot.
        store
            .publish(
                &[key],
                store.current().unwrap(),
                "semantic-project/1",
                false,
            )
            .unwrap();
        units.push(key);
        expected.push((key, project));
    }
    assert_eq!(units.len(), 26);
    let snapshot = store.current().unwrap().unwrap();
    store.close().unwrap();
    let store = StructuralStore::open(Some(&path), None).unwrap();
    assert_eq!(store.current().unwrap(), Some(snapshot));
    for (unit, ir) in expected {
        let loaded: StructuralIr = store.load_unit(unit).unwrap();
        assert_eq!(
            serde_json::to_value(loaded).unwrap(),
            serde_json::to_value(ir).unwrap()
        );
    }
}
