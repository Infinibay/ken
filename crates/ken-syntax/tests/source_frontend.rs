//! Full original source IR, including lexical declarations and semantic evidence.
use flate2::read::GzDecoder;
use ken_program::{
    StructuralIr,
    control::{structured_control, syntax_contexts},
    normalize_syntax,
};
use ken_store::structural::StructuralStore;
use ken_syntax::{GrammarCatalog, Language, structural::lower_source};
use serde::Deserialize;
use serde_json::{Value, value::RawValue};
use sha2::{Digest, Sha256};
use std::{io::Read, path::PathBuf};
#[derive(Deserialize)]
struct Case {
    name: String,
    language: Language,
    path: String,
    source: Vec<u8>,
    result: Box<RawValue>,
    control: Box<RawValue>,
}
fn catalog() -> GrammarCatalog {
    GrammarCatalog::prepared(&PathBuf::from(
        std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
    ))
    .unwrap()
}
fn cases() -> Vec<Case> {
    let bytes = include_bytes!("fixtures/source-frontend-reference.json.gz");
    assert_eq!(bytes.len(), 318911);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "6eb76c8f73bfc3602c5d28810032d72366543184c531b8b5b936fccf7f72366f"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    #[derive(Deserialize)]
    struct Corpus {
        cases: Vec<Case>,
    }
    let v: Corpus = serde_json::from_str(&text).unwrap();
    assert_eq!(v.cases.len(), 88);
    v.cases
}
fn stable(mut value: Value) -> Value {
    // Python stores tree_sitter.Node.id here: a process-specific native address.
    // Its stable lexical identity is already the entity's @block-start suffix.
    for (id, entity) in value["entities"].as_object_mut().unwrap() {
        if let Some(raw) = entity["attrs"].get("block_scope") {
            assert!(
                raw.as_u64().is_some_and(|n| n > 0),
                "non-address scope marker {id}"
            );
            let start = id.rsplit_once('@').unwrap().1.parse::<usize>().unwrap();
            entity["attrs"]["block_scope"] = format!("block-at:{start}").into();
        }
    }
    value
}
fn mismatch(a: &Value, b: &Value, path: &str) -> Option<String> {
    if a == b {
        return None;
    }
    match (a, b) {
        (Value::Array(a), Value::Array(b)) => a
            .iter()
            .zip(b)
            .enumerate()
            .find_map(|(i, (a, b))| mismatch(a, b, &format!("{path}/{i}")))
            .or_else(|| Some(format!("{path}: array lengths {} != {}", a.len(), b.len()))),
        (Value::Object(a), Value::Object(b)) => {
            let missing = b.keys().filter(|k| !a.contains_key(*k)).collect::<Vec<_>>();
            let extra = a.keys().filter(|k| !b.contains_key(*k)).collect::<Vec<_>>();
            if !missing.is_empty() || !extra.is_empty() {
                Some(format!("{path}: missing {missing:?}, extra {extra:?}"))
            } else {
                a.iter()
                    .find_map(|(k, a)| mismatch(a, &b[k], &format!("{path}/{k}")))
            }
        }
        _ => Some(format!("{path}: actual={a}, expected={b}")),
    }
}
fn compare(ir: &StructuralIr, expected: &RawValue) -> Option<String> {
    mismatch(
        &stable(serde_json::to_value(ir).unwrap()),
        &stable(serde_json::from_str(expected.get()).unwrap()),
        "",
    )
}
#[test]
fn full_original_source_entities_attributes_bindings_and_ordered_facts_match() {
    let catalog = catalog();
    let mut errors = Vec::new();
    for case in cases() {
        let ir = lower_source(&catalog, case.language, &case.source, &case.path).unwrap();
        if let Some(diff) = compare(&ir, &case.result) {
            errors.push(format!("{}: {diff}", case.name));
        }
    }
    assert!(errors.is_empty(), "{}", errors.join("\n"));
}
#[test]
fn full_source_cfg_contexts_and_syntax_programs_preserve_the_original_contract() {
    let catalog = catalog();
    let mut errors = Vec::new();
    for case in cases() {
        let mut ir = lower_source(&catalog, case.language, &case.source, &case.path).unwrap();
        structured_control(&mut ir, None).unwrap();
        syntax_contexts(&mut ir).unwrap();
        if let Some(diff) = compare(&ir, &case.control) {
            errors.push(format!("{}: {diff}", case.name));
        }
        normalize_syntax(&ir).unwrap().validate().unwrap();
    }
    assert!(errors.is_empty(), "{}", errors.join("\n"));
}
#[test]
fn complete_native_source_units_publish_reopen_and_retain_semantic_ir() {
    let catalog = catalog();
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("frontend.sqlite");
    let mut store = StructuralStore::open(Some(&path), None).unwrap();
    let mut units = Vec::new();
    let mut expected = Vec::new();
    for case in cases() {
        let ir = lower_source(&catalog, case.language, &case.source, &case.path).unwrap();
        let unit = store
            .put_unit(
                &case.name,
                &ir,
                "source-revision",
                "full-source/1",
                ir.diagnostics.is_empty(),
            )
            .unwrap();
        units.push(unit);
        expected.push((unit, ir));
    }
    let snapshot = store.publish(&units, None, "full-source/1", false).unwrap();
    store.close().unwrap();
    let mut store = StructuralStore::open(Some(&path), None).unwrap();
    assert_eq!(store.current().unwrap(), Some(snapshot));
    for (unit, ir) in expected {
        assert_eq!(
            serde_json::to_value(store.load_unit(unit).unwrap()).unwrap(),
            serde_json::to_value(&ir).unwrap()
        );
        assert_eq!(
            store.operations(unit, None).unwrap().operations.len(),
            ir.operations.len()
        );
    }
}

#[test]
fn new_multi_source_groups_reach_the_original_nominal_graph_from_native_bytes() {
    #[derive(Deserialize)]
    struct Source {
        path: String,
        language: Language,
        source: String,
    }
    #[derive(Deserialize)]
    struct Project {
        name: String,
        sources: Option<Vec<Source>>,
        units: Vec<Box<RawValue>>,
        result: Box<RawValue>,
    }
    #[derive(Deserialize)]
    struct Corpus {
        cases: Vec<Project>,
    }
    let mut text = String::new();
    GzDecoder::new(
        &include_bytes!("../../ken-program/tests/fixtures/nominal-project-reference.json.gz")[..],
    )
    .read_to_string(&mut text)
    .unwrap();
    let corpus: Corpus = serde_json::from_str(&text).unwrap();
    let catalog = catalog();
    let mut errors = Vec::new();
    for case in corpus.cases {
        let Some(sources) = case.sources else {
            continue;
        };
        let mut units = Vec::new();
        for (source, expected) in sources.iter().zip(&case.units) {
            let unit = lower_source(
                &catalog,
                source.language,
                source.source.as_bytes(),
                &source.path,
            )
            .unwrap();
            if let Some(diff) = compare(&unit, expected) {
                errors.push(format!("{} source {}: {diff}", case.name, source.path));
            }
            units.push(unit);
        }
        let prefix: usize = units.iter().map(|u| u.facts.len()).sum();
        let actual = ken_program::project::link_nominal(&units).unwrap();
        let canonical = |mut value: Value| {
            let facts = value["facts"].as_array_mut().unwrap();
            let mut derived = facts.split_off(prefix);
            derived.sort_by_key(Value::to_string);
            facts.extend(derived);
            stable(value)
        };
        let a = canonical(serde_json::to_value(actual).unwrap());
        let b = canonical(serde_json::from_str(case.result.get()).unwrap());
        if let Some(diff) = mismatch(&a, &b, "") {
            errors.push(format!("{} graph: {diff}", case.name));
        }
    }
    assert!(errors.is_empty(), "{}", errors.join("\n"));
}

#[test]
fn source_regexes_preserve_frozen_python_word_characters() {
    #[derive(Deserialize)]
    struct UnicodeCase {
        name: String,
        path: String,
        language: Language,
        source: String,
        result: Box<RawValue>,
    }
    #[derive(Deserialize)]
    struct Corpus {
        cases: Vec<UnicodeCase>,
    }
    let text = include_str!("fixtures/source-unicode-reference.json");
    assert_eq!(text.len(), 30079);
    assert_eq!(
        format!("{:x}", Sha256::digest(text.as_bytes())),
        "20c129b60a71e20c455112ca1463641ae9b3a25aeb50ac2209d9789fa4051987"
    );
    let corpus: Corpus = serde_json::from_str(text).unwrap();
    let catalog = catalog();
    let mut errors = Vec::new();
    for case in corpus.cases {
        let ir = lower_source(&catalog, case.language, case.source.as_bytes(), &case.path).unwrap();
        if let Some(diff) = compare(&ir, &case.result) {
            errors.push(format!("{}: {diff}", case.name));
        }
    }
    assert!(errors.is_empty(), "{}", errors.join("\n"));
}
