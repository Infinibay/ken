//! Exact original statement routes, lexical evidence and syntax context ordering.
use flate2::read::GzDecoder;
use ken_program::{
    StructuralIr,
    control::{lexical_execution, structured_control, syntax_contexts},
};
use serde::Deserialize;
use serde_json::{Value, value::RawValue};
use sha2::{Digest, Sha256};
use std::{collections::BTreeSet, io::Read};

#[derive(Deserialize)]
struct Case {
    name: String,
    input: Box<RawValue>,
    status: Value,
    execution: Box<RawValue>,
    control: Box<RawValue>,
    contexts: Box<RawValue>,
    options: Options,
}
#[derive(Deserialize)]
struct Options {
    #[serde(default)]
    invalid: bool,
    diagnostic_paths: Option<BTreeSet<String>>,
}
fn cases() -> Vec<Case> {
    let exceptions = include_bytes!("../resources/python-exceptions.json");
    assert_eq!(exceptions.len(), 12630);
    assert_eq!(
        format!("{:x}", Sha256::digest(exceptions)),
        "aadc7e2be8f377e114bb7d69ecf90e492a8f6ac33716973027010926d23353c6"
    );
    let bytes = include_bytes!("fixtures/control-core-reference.json.gz");
    assert_eq!(bytes.len(), 88797);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "5fdbec695fd653bb31a6a737b2a9a57230c99035f616bdcbd1e8e26ffc8c090a"
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
    assert_eq!(corpus.cases.len(), 23);
    corpus.cases
}
fn mismatch(actual: &Value, expected: &Value, path: &str) -> Option<String> {
    if actual == expected {
        return None;
    }
    match (actual, expected) {
        (Value::Array(a), Value::Array(b)) if a.len() == b.len() => a
            .iter()
            .zip(b)
            .enumerate()
            .find_map(|(i, (a, b))| mismatch(a, b, &format!("{path}/{i}"))),
        (Value::Object(a), Value::Object(b)) if a.keys().eq(b.keys()) => a
            .iter()
            .find_map(|(k, a)| mismatch(a, &b[k], &format!("{path}/{k}"))),
        _ => Some(format!("{path}: actual={actual}, expected={expected}")),
    }
}
fn compare(actual: &impl serde::Serialize, expected: &RawValue, name: &str) {
    let actual = serde_json::to_value(actual).unwrap();
    let expected = serde_json::from_str(expected.get()).unwrap();
    if let Some(diff) = mismatch(&actual, &expected, "") {
        panic!("{name}: {diff}");
    }
}
#[test]
fn original_lexical_execution_including_hoisting_invalid_and_reversed_operations() {
    for case in cases() {
        let mut graph = StructuralIr::from_json(case.input.get()).unwrap();
        // The original frontend already annotates operations before returning IR.
        // Rebuild annotations here so the producer cannot mask a missing write.
        for operation in &mut graph.operations {
            operation.attrs.remove("execution");
        }
        let status = lexical_execution(&mut graph, case.options.invalid).unwrap();
        assert_eq!(
            serde_json::to_value(status).unwrap(),
            case.status,
            "{}",
            case.name
        );
        compare(&graph, &case.execution, &case.name);
    }
}
#[test]
fn original_cfg_completion_dispatch_suspension_and_partial_coverage() {
    for case in cases() {
        let mut graph = StructuralIr::from_json(case.execution.get()).unwrap();
        structured_control(&mut graph, case.options.diagnostic_paths.as_ref()).unwrap();
        compare(&graph, &case.control, &case.name);
    }
}
#[test]
fn original_syntax_call_contexts_and_result_discarding() {
    for case in cases() {
        let mut graph = StructuralIr::from_json(case.control.get()).unwrap();
        syntax_contexts(&mut graph).unwrap();
        compare(&graph, &case.contexts, &case.name);
    }
}

#[test]
fn incomplete_call_ranges_do_not_abort_unrelated_contexts_or_coerce_text_offsets() {
    let case = cases().remove(0);
    let source = StructuralIr::from_json(case.control.get()).unwrap();
    let call = source
        .entities
        .iter()
        .find(|(_, e)| e.kind == "CALL")
        .unwrap()
        .1
        .id
        .clone();
    let expected: Value = serde_json::from_str(case.contexts.get()).unwrap();
    for key in ["start_byte", "end_byte"] {
        for value in [
            Value::Null,
            Value::String("1".into()),
            serde_json::json!(1.5),
            serde_json::json!(1e50),
            Value::Bool(true),
        ] {
            let mut graph = source.clone();
            graph
                .entities
                .iter_mut()
                .find(|(_, e)| e.id == call)
                .unwrap()
                .1
                .attrs
                .insert(key.into(), serde_json::value::to_raw_value(&value).unwrap());
            let mut wanted = expected.clone();
            wanted["entities"][&call]["attrs"][key] = value;
            wanted["facts"].as_array_mut().unwrap().retain(|f| {
                !((f["relation"] == "SYNTAX_NODE" && f["subject"] == call)
                    || (f["relation"] == "DISCARDS_RESULT" && f["object"] == call))
            });
            syntax_contexts(&mut graph).unwrap();
            assert_eq!(serde_json::to_value(&graph).unwrap(), wanted, "{key}");
        }
        let mut graph = source.clone();
        let entity = &mut graph
            .entities
            .iter_mut()
            .find(|(_, e)| e.id == call)
            .unwrap()
            .1;
        let original: Value = serde_json::from_str(entity.attrs[key].get()).unwrap();
        let float = serde_json::json!(original.as_i64().unwrap() as f64);
        entity
            .attrs
            .insert(key.into(), serde_json::value::to_raw_value(&float).unwrap());
        let mut wanted = expected.clone();
        wanted["entities"][&call]["attrs"][key] = float;
        syntax_contexts(&mut graph).unwrap();
        assert_eq!(
            serde_json::to_value(&graph).unwrap(),
            wanted,
            "equal numeric coordinate"
        );
    }
}
