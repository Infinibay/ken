//! Frozen original local snapshots and bounded statement completion.
use flate2::read::GzDecoder;
use ken_program::{
    StructuralIr,
    control::{normal_completion, sequential_returns, structured_control, syntax_contexts},
};
use serde::Deserialize;
use serde_json::{Value, value::RawValue};
use sha2::{Digest, Sha256};
use std::{collections::BTreeSet, io::Read};
#[derive(Deserialize)]
struct Case {
    name: String,
    input: Box<RawValue>,
    diagnostic_paths: BTreeSet<String>,
    result: Value,
    flow: Box<RawValue>,
    controlled: Box<RawValue>,
    normal: Box<RawValue>,
}
fn cases() -> Vec<Case> {
    let bytes = include_bytes!("fixtures/local-origins-reference.json.gz");
    assert_eq!(bytes.len(), 1079881);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "0647b1a8794c317dc898439516c0339cfe7cb97f72e7d4d98be10b66d2a15730"
    );
    let strings = include_bytes!("../../ken-text/src/string-properties15.json");
    assert_eq!(strings.len(), 17857);
    assert_eq!(
        format!("{:x}", Sha256::digest(strings)),
        "2f3ee56b7044637f98cd6dbb15c97458bfa34655919943c067191c470cff9152"
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
    assert_eq!(corpus.cases.len(), 53);
    corpus.cases
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
        (Value::Object(a), Value::Object(b)) if a.keys().eq(b.keys()) => a
            .iter()
            .find_map(|(k, a)| mismatch(a, &b[k], &format!("{path}/{k}"))),
        _ => Some(format!("{path}: actual={a}, expected={b}")),
    }
}
fn compare(ir: &StructuralIr, expected: &RawValue) -> Option<String> {
    mismatch(
        &serde_json::to_value(ir).unwrap(),
        &serde_json::from_str(expected.get()).unwrap(),
        "",
    )
}
#[test]
fn original_local_return_argument_read_expression_and_field_origins_match() {
    let mut errors = Vec::new();
    for case in cases() {
        let mut ir = StructuralIr::from_json(case.input.get()).unwrap();
        let origins = sequential_returns(&mut ir, Some(&case.diagnostic_paths)).unwrap();
        let origins = origins
            .into_iter()
            .map(|((owner, value), origins)| serde_json::json!([owner, value, origins]))
            .collect::<Vec<_>>();
        if serde_json::to_value(origins).unwrap() != case.result {
            errors.push(format!("{}: returned origin map differs", case.name));
        }
        if let Some(diff) = compare(&ir, &case.flow) {
            errors.push(format!("{}: {diff}", case.name));
        }
    }
    assert!(errors.is_empty(), "{}", errors.join("\n"));
}
#[test]
fn original_statement_completion_and_handler_fallthrough_match() {
    let mut errors = Vec::new();
    for case in cases() {
        let mut ir = StructuralIr::from_json(case.controlled.get()).unwrap();
        normal_completion(&mut ir).unwrap();
        if let Some(diff) = compare(&ir, &case.normal) {
            errors.push(format!("{}: {diff}", case.name));
        }
    }
    assert!(errors.is_empty(), "{}", errors.join("\n"));
}
#[test]
fn complete_nominal_flow_control_and_completion_pipeline_matches() {
    let mut errors = Vec::new();
    for case in cases() {
        let mut ir = StructuralIr::from_json(case.input.get()).unwrap();
        sequential_returns(&mut ir, Some(&case.diagnostic_paths)).unwrap();
        structured_control(&mut ir, Some(&case.diagnostic_paths)).unwrap();
        syntax_contexts(&mut ir).unwrap();
        normal_completion(&mut ir).unwrap();
        if let Some(diff) = compare(&ir, &case.normal) {
            errors.push(format!("{}: {diff}", case.name));
        }
    }
    assert!(errors.is_empty(), "{}", errors.join("\n"));
}
