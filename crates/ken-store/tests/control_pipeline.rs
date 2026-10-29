//! Control evidence survives publication without turning continuations into syntax.
use flate2::read::GzDecoder;
use ken_program::{
    StructuralIr,
    control::{lexical_execution, structured_control, syntax_contexts},
};
use ken_store::structural::{NodeFilter, StructuralStore};
use serde::Deserialize;
use serde_json::{Value, value::RawValue};
use std::{collections::BTreeSet, io::Read};
#[derive(Deserialize)]
struct Options {
    #[serde(default)]
    invalid: bool,
    diagnostic_paths: Option<BTreeSet<String>>,
}
#[derive(Deserialize)]
struct Case {
    name: String,
    input: Box<RawValue>,
    contexts: Box<RawValue>,
    options: Options,
}
#[derive(Deserialize)]
struct Corpus {
    cases: Vec<Case>,
}
#[test]
fn enriched_control_ir_publishes_and_reopens_with_syntax_membership_intact() {
    let mut text = String::new();
    GzDecoder::new(
        &include_bytes!("../../ken-program/tests/fixtures/control-core-reference.json.gz")[..],
    )
    .read_to_string(&mut text)
    .unwrap();
    let corpus: Corpus = serde_json::from_str(&text).unwrap();
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("control.sqlite");
    let mut store = StructuralStore::open(Some(&path), None).unwrap();
    let mut units = Vec::new();
    let mut expected = Vec::new();
    for case in corpus.cases {
        let mut ir = StructuralIr::from_json(case.input.get()).unwrap();
        let syntax = ir.operations.len();
        lexical_execution(&mut ir, case.options.invalid).unwrap();
        structured_control(&mut ir, case.options.diagnostic_paths.as_ref()).unwrap();
        syntax_contexts(&mut ir).unwrap();
        assert_eq!(ir.operations.len(), syntax);
        let reference: Value = serde_json::from_str(case.contexts.get()).unwrap();
        assert_eq!(
            serde_json::to_value(&ir).unwrap(),
            reference,
            "{}",
            case.name
        );
        let unit = store
            .put_unit(&case.name, &ir, "source-hash", "control-core/1", false)
            .unwrap();
        units.push(unit);
        expected.push((unit, ir, reference));
    }
    let snapshot = store
        .publish(&units, None, "control-core/1", false)
        .unwrap();
    store.close().unwrap();
    let mut store = StructuralStore::open(Some(&path), None).unwrap();
    assert_eq!(store.current().unwrap(), Some(snapshot));
    for (unit, ir, reference) in expected {
        assert_eq!(
            serde_json::to_value(store.load_unit(unit).unwrap()).unwrap(),
            reference
        );
        let operations = store.operations(unit, None).unwrap();
        assert_eq!(operations.operations.len(), ir.operations.len());
        assert!(
            operations
                .operations
                .iter()
                .all(|op| !op.id.contains("::continuation-"))
        );
    }
    let mut scan = store.prepare_scan(snapshot, NodeFilter::default()).unwrap();
    let rows = scan.rows().unwrap().collect::<Result<Vec<_>, _>>().unwrap();
    assert!(!rows.is_empty());
    assert!(rows.iter().all(|n| !n.local_id.contains("::continuation-")));
}
