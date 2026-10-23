//! Complete persisted programs retain their public schema and actual validation.
use ken_program::{Program, StructuralIr, body_ranges};
use serde::Deserialize;
use serde_json::value::RawValue;

#[derive(Deserialize)]
struct Row {
    id: String,
    input: Box<RawValue>,
    result: Option<Program>,
    error: Option<serde_json::Value>,
    bodies: Option<serde_json::Value>,
}
#[derive(Deserialize)]
struct Corpus {
    programs: Vec<Row>,
    codecs: Vec<Row>,
}
fn corpus() -> Corpus {
    serde_json::from_str(include_str!("fixtures/program-reference.json")).unwrap()
}
#[test]
fn every_original_program_codec_and_body_range_roundtrips() {
    let corpus = corpus();
    assert_eq!(corpus.programs.len(), 90);
    for row in &corpus.programs {
        let ir = StructuralIr::from_json(row.input.get()).unwrap();
        let encoded = serde_json::to_string(&ir).unwrap();
        let again = StructuralIr::from_json(&encoded).unwrap();
        assert_eq!(
            serde_json::to_string(&again).unwrap(),
            encoded,
            "IR {}",
            row.id
        );
        if let Some(expected) = &row.result {
            expected.validate().unwrap();
            assert_eq!(
                Program::from_json(&expected.to_json().unwrap()).unwrap(),
                *expected,
                "codec {}",
                row.id
            );
            assert_eq!(
                serde_json::to_value(body_ranges(expected)).unwrap(),
                *row.bodies.as_ref().unwrap(),
                "bodies {}",
                row.id
            );
        }
    }
    assert_eq!(corpus.codecs.len(), 26);
    for row in &corpus.codecs {
        let actual = Program::from_json(row.input.get());
        if row.error.is_some() {
            assert!(actual.is_err(), "lost original error {}", row.id);
        } else {
            assert_eq!(
                actual.unwrap(),
                *row.result.as_ref().unwrap(),
                "codec {}",
                row.id
            );
        }
    }
}
#[test]
fn ordered_ir_entities_and_ignored_non_scalar_attributes_survive() {
    let input = r#"{"path":"example","language":"python","version":"1.88.0","entities":{"z":{"id":"z","kind":"CLASS","name":"first","path":"example","line":1,"end_line":1},"a":{"id":"a","kind":"CLASS","name":"second","path":"example","line":1,"end_line":1},"z":{"id":"z","kind":"CLASS","name":"last","path":"example","line":1,"end_line":1,"attrs":{"unused":"\ud800"}}},"operations":[],"facts":[],"capabilities":[],"diagnostics":[]}"#;
    let ir = StructuralIr::from_json(input).unwrap();
    assert_eq!(
        ir.entities
            .iter()
            .map(|(key, e)| (key.as_str(), e.name.as_str()))
            .collect::<Vec<_>>(),
        vec![("z", "last"), ("a", "second")]
    );
    let round = serde_json::to_string(&ir).unwrap();
    assert!(round.contains(r#""unused":"\ud800""#));
    assert!(StructuralIr::from_json(&input.replace("1.88.0", "future")).is_err());
}
