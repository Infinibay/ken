use ken_query::{BackendPreference, ParseLimits, authoring};
use serde_json::Value;
use std::{collections::BTreeMap, io::Read};
fn corpus() -> Value {
    let mut raw = String::new();
    flate2::read::GzDecoder::new(&include_bytes!("fixtures/authoring-reference.json.gz")[..])
        .read_to_string(&mut raw)
        .unwrap();
    serde_json::from_str(&raw).unwrap()
}
#[test]
fn authoring_capabilities_come_from_native_compiler_and_syntax_owners() {
    assert_eq!(authoring::capabilities(), corpus()["capabilities"]);
}
#[test]
fn compile_only_explanation_preserves_diagnostics_without_acquiring_sources() {
    for case in corpus()["cases"].as_array().unwrap() {
        let result = ken_query::parse(
            case["source"].as_str().unwrap(),
            "<query>",
            ParseLimits::default(),
        )
        .map_err(|e| e.to_string())
        .and_then(|tree| {
            ken_query::compile(&tree, None, &BTreeMap::new(), BackendPreference::Automatic)
                .map_err(|e| e.to_string())
        })
        .and_then(|compiled| {
            authoring::explain(&compiled, case["backend"].as_str().unwrap())
                .map_err(|e| e.to_string())
        });
        if let Some(expected) = case.get("result") {
            assert_eq!(result.unwrap(), *expected, "{}", case["name"]);
        } else {
            assert!(
                result.is_err(),
                "{} must reject: {:?}",
                case["name"],
                result
            );
        }
    }
}
