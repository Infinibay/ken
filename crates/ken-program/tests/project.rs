//! Original nominal linking boundary; graph expansions of Python sets are unordered.
use flate2::read::GzDecoder;
use ken_program::{
    ProgramError, StructuralIr,
    project::{link_nominal, link_nominal_owned, link_nominal_with_check},
};
use serde::Deserialize;
use serde_json::{Value, value::RawValue};
use sha2::{Digest, Sha256};
use std::io::Read;
#[derive(Deserialize)]
struct Case {
    name: String,
    units: Vec<Box<RawValue>>,
    result: Box<RawValue>,
    checks: usize,
}
fn cases() -> Vec<Case> {
    let bytes = include_bytes!("fixtures/nominal-project-reference.json.gz");
    assert_eq!(bytes.len(), 423530);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "104c44a62672857cd9d0dc9c059f26703a29364be95def90fc8bce116ec5ab37"
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
    assert_eq!(corpus.cases.len(), 41);
    corpus.cases
}
fn canonical(mut ir: Value, prefix: usize) -> Value {
    let facts = ir["facts"].as_array_mut().unwrap();
    let mut derived = facts.split_off(prefix);
    derived.sort_by_key(serde_json::Value::to_string);
    facts.extend(derived);
    ir
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
            .or_else(|| Some(format!("{path}: array length {} != {}", a.len(), b.len()))),
        (Value::Object(a), Value::Object(b)) if a.keys().eq(b.keys()) => a
            .iter()
            .find_map(|(k, a)| mismatch(a, &b[k], &format!("{path}/{k}"))),
        _ => Some(format!("{path}: actual={a}, expected={b}")),
    }
}
#[test]
fn original_nominal_types_imports_calls_closures_and_virtual_signatures_match() {
    let mut errors = Vec::new();
    for case in cases() {
        let units = case
            .units
            .iter()
            .map(|raw| StructuralIr::from_json(raw.get()).unwrap())
            .collect::<Vec<_>>();
        let mut checks = 0;
        let actual = link_nominal_with_check(&units, || {
            checks += 1;
            Ok(())
        })
        .unwrap();
        assert_eq!(checks, case.checks, "{} budget checkpoints", case.name);
        let prefix = units.iter().map(|u| u.facts.len()).sum();
        let a = serde_json::to_value(&actual).unwrap();
        let b: Value = serde_json::from_str(case.result.get()).unwrap();
        assert_eq!(
            &a["facts"].as_array().unwrap()[..prefix],
            &b["facts"].as_array().unwrap()[..prefix],
            "source prefix {} ",
            case.name
        );
        if let Some(diff) = mismatch(&canonical(a, prefix), &canonical(b, prefix), "") {
            errors.push(format!("{}: {diff}", case.name));
        }
    }
    assert!(errors.is_empty(), "{}", errors.join("\n"));
}
#[test]
fn owned_and_immutable_inputs_preserve_identical_results_without_aliasing() {
    for case in cases() {
        let units = case
            .units
            .iter()
            .map(|raw| StructuralIr::from_json(raw.get()).unwrap())
            .collect::<Vec<_>>();
        let before = serde_json::to_string(&units).unwrap();
        let borrowed = link_nominal(&units).unwrap();
        let owned = link_nominal_owned(units.clone()).unwrap();
        assert_eq!(
            serde_json::to_string(&borrowed).unwrap(),
            serde_json::to_string(&owned).unwrap(),
            "{}",
            case.name
        );
        assert_eq!(serde_json::to_string(&units).unwrap(), before);
    }
}
#[test]
fn cancellation_cannot_mutate_inputs_or_return_partial_project_state() {
    let case = cases()
        .into_iter()
        .find(|c| c.name == "all_frontends")
        .unwrap();
    let units = case
        .units
        .iter()
        .map(|raw| StructuralIr::from_json(raw.get()).unwrap())
        .collect::<Vec<_>>();
    let before = serde_json::to_string(&units).unwrap();
    for stop in [1, 2, units.len() + 1, units.len() + 2, case.checks] {
        let mut checks = 0;
        let result = link_nominal_with_check(&units, || {
            checks += 1;
            if checks == stop {
                Err(ProgramError::Invalid("test budget reached"))
            } else {
                Ok(())
            }
        });
        assert!(result.is_err(), "stop {stop}");
        assert_eq!(checks, stop);
        assert_eq!(serde_json::to_string(&units).unwrap(), before);
    }
}

#[test]
fn unrelated_fact_payload_remains_lossless_and_uninterpreted() {
    let case = cases()
        .into_iter()
        .find(|c| c.name == "single_py_storage")
        .unwrap();
    let mut units = case
        .units
        .iter()
        .map(|raw| StructuralIr::from_json(raw.get()).unwrap())
        .collect::<Vec<_>>();
    for payload in [
        r#""\ud800""#.to_owned(),
        "1e400".to_owned(),
        format!("{}0{}", "[".repeat(150), "]".repeat(150)),
    ] {
        units[0].facts[0].attrs.insert(
            "opaque_payload".into(),
            RawValue::from_string(payload.clone()).unwrap(),
        );
        let graph =
            link_nominal(&units).expect("nominal must not decode unrelated fact attributes");
        assert_eq!(graph.facts[0].attrs["opaque_payload"].get(), payload);
    }
}
#[test]
fn mixed_path_projects_only_require_commonpath_for_rust_crate_imports() {
    fn unit(path: &str, language: &str) -> StructuralIr {
        StructuralIr::from_json(&serde_json::json!({"path":path,"language":language,"entities":{format!("{path}::module"):{"id":format!("{path}::module"),"kind":"MODULE","name":path,"path":path,"line":1,"end_line":1}},"operations":[],"facts":[],"capabilities":["syntax"],"diagnostics":[],"version":"1.88.0"}).to_string()).unwrap()
    }
    let relative = unit("a.py", "python");
    let absolute = unit("/tmp/b.py", "python");
    assert!(link_nominal(&[relative, absolute.clone()]).is_ok());
    let mut rust = unit("src/a.rs", "rust");
    assert!(link_nominal(&[rust.clone(), absolute.clone()]).is_ok());
    rust.facts.push(ken_program::Fact {
        subject: "src/a.rs::module".into(),
        relation: "IMPORT_SYNTAX".into(),
        object: "use crate::model::Product;".into(),
        attrs: std::collections::BTreeMap::from([(
            "language".into(),
            RawValue::from_string("\"rust\"".into()).unwrap(),
        )]),
        evidence: vec![],
    });
    assert!(link_nominal(&[rust, absolute]).is_err());
}
