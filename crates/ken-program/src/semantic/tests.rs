//! Original downstream evidence: accepted upstream observations are frozen inputs.
use super::*;
use flate2::read::GzDecoder;
use serde::Deserialize;
use serde_json::value::RawValue;
use sha2::{Digest, Sha256};
use std::io::Read;
#[derive(Deserialize)]
struct Case {
    name: String,
    input: Box<RawValue>,
    diagnostic_paths: BTreeSet<String>,
    result: Box<RawValue>,
    checks: usize,
    units: Option<Vec<Box<RawValue>>>,
}
fn cases() -> Vec<Case> {
    let bytes = include_bytes!("../../tests/fixtures/project-semantics-reference.json.gz");
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
    let c: Corpus = serde_json::from_str(&text).unwrap();
    assert_eq!(c.cases.len(), 79);
    c.cases
}
fn canonical(mut ir: Value) -> Value {
    ir["facts"]
        .as_array_mut()
        .unwrap()
        .sort_by_key(Value::to_string);
    ir
}
fn compare(ir: &StructuralIr, expected: &RawValue, name: &str) -> bool {
    let actual = canonical(serde_json::to_value(ir).unwrap());
    let expected = canonical(serde_json::from_str(expected.get()).unwrap());
    if actual == expected {
        return true;
    }
    let path =
        std::env::temp_dir().join(format!("ken-semantic-mismatch-{}", name.replace('/', "_")));
    std::fs::create_dir_all(&path).unwrap();
    std::fs::write(
        path.join("actual.json"),
        serde_json::to_vec(&actual).unwrap(),
    )
    .unwrap();
    std::fs::write(
        path.join("expected.json"),
        serde_json::to_vec(&expected).unwrap(),
    )
    .unwrap();
    eprintln!("{name} differs: {}", path.display());
    false
}
#[test]
fn all_original_downstream_project_phases_preserve_complete_evidence() {
    let mut failures = vec![];
    for c in cases() {
        let ir = StructuralIr::from_json(c.input.get()).unwrap();
        let result = enrich(ir, &c.diagnostic_paths, &mut || Ok(()))
            .unwrap_or_else(|e| panic!("{}: {e}", c.name));
        if !compare(&result, &c.result, &c.name) {
            failures.push(c.name);
        }
    }
    assert!(
        failures.is_empty(),
        "project semantic mismatches: {failures:?}"
    );
}
#[test]
fn full_linker_matches_original_new_inputs_and_checkpoint_counts() {
    let mut count = 0;
    for c in cases() {
        let Some(raw) = c.units else {
            continue;
        };
        let units = raw
            .iter()
            .map(|r| StructuralIr::from_json(r.get()).unwrap())
            .collect::<Vec<_>>();
        let before = units
            .iter()
            .map(|u| serde_json::to_string(u).unwrap())
            .collect::<Vec<_>>();
        let mut checks = 0;
        let actual = crate::project::link_project_with_check(&units, || {
            checks += 1;
            Ok(())
        })
        .unwrap();
        assert!(compare(&actual, &c.result, &c.name), "{}", c.name);
        assert_eq!(checks, c.checks, "{} checks", c.name);
        assert_eq!(
            before,
            units
                .iter()
                .map(|u| serde_json::to_string(u).unwrap())
                .collect::<Vec<_>>()
        );
        let owned = crate::project::link_project_owned(units).unwrap();
        assert_eq!(
            canonical(serde_json::to_value(owned).unwrap()),
            canonical(serde_json::to_value(actual).unwrap())
        );
        count += 1;
    }
    assert_eq!(count, 26);
}
#[test]
fn full_linker_cancellation_drops_partial_results_and_preserves_inputs() {
    let c = cases()
        .into_iter()
        .find(|c| c.name == "snapshot_python")
        .unwrap();
    let units = c
        .units
        .unwrap()
        .iter()
        .map(|r| StructuralIr::from_json(r.get()).unwrap())
        .collect::<Vec<_>>();
    let before = serde_json::to_string(&units[0]).unwrap();
    for stop in 1..=c.checks {
        let mut seen = 0;
        let result = crate::project::link_project_with_check(&units, || {
            seen += 1;
            if seen == stop {
                Err(ProgramError::Invalid("cancel semantic project"))
            } else {
                Ok(())
            }
        });
        assert!(result.is_err(), "checkpoint {stop}");
        assert_eq!(seen, stop);
        assert_eq!(before, serde_json::to_string(&units[0]).unwrap());
    }
    let mut seen = 0;
    let result = crate::project::link_project_owned_with_check(units, || {
        seen += 1;
        Err(ProgramError::Invalid("cancel owned project"))
    });
    assert!(result.is_err());
    assert_eq!(seen, 1);
}

#[test]
fn full_project_preserves_opaque_metadata_in_entity_and_operation_publication() {
    let case = cases()
        .into_iter()
        .find(|c| c.name == "threads_python")
        .unwrap();
    let mut units = case
        .units
        .unwrap()
        .iter()
        .map(|r| StructuralIr::from_json(r.get()).unwrap())
        .collect::<Vec<_>>();
    let module = format!("{}::module", units[0].path);
    let nested = format!("{}0{}", "[".repeat(150), "]".repeat(150));
    let values = [r#""\ud800""#.to_string(), "1e400".into(), nested];
    for (i, text) in values.iter().enumerate() {
        let key = format!("opaque{i}");
        let raw = serde_json::value::RawValue::from_string(text.clone()).unwrap();
        units[0]
            .entities
            .iter_mut()
            .find(|(id, _)| id == &module)
            .unwrap()
            .1
            .attrs
            .insert(key.clone(), raw.clone());
        units[0].operations[0]
            .attrs
            .insert(key.clone(), raw.clone());
        units[0].facts[0].attrs.insert(key, raw);
    }
    let original = serde_json::to_string(&units).unwrap();
    let result = crate::project::link_project(&units).unwrap();
    assert_eq!(original, serde_json::to_string(&units).unwrap());
    let entity = result
        .entities
        .iter()
        .find(|(id, _)| id == &module)
        .unwrap();
    let entity_fact = result
        .facts
        .iter()
        .find(|f| f.subject == module && f.relation == "ENTITY")
        .unwrap();
    let op = &units[0].operations[0];
    let op_fact = result
        .facts
        .iter()
        .find(|f| f.subject == op.id && f.relation == "OPERATION")
        .unwrap();
    for (i, text) in values.iter().enumerate() {
        let key = format!("opaque{i}");
        for attrs in [
            &entity.1.attrs,
            &entity_fact.attrs,
            &op_fact.attrs,
            &result.facts[0].attrs,
        ] {
            assert_eq!(attrs[&key].get(), text);
        }
    }
}

#[test]
fn indexed_argument_summaries_preserve_original_duplicates_spreads_and_position_equality() {
    let bytes = include_bytes!("../../tests/fixtures/argument-summary-reference.json");
    assert_eq!(bytes.len(), 26486);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "aca57c277d07cf8b2b4f3b071083653b755a743de642036377d75e0c7450784a"
    );
    let corpus: Value = serde_json::from_slice(bytes).unwrap();
    let cases = corpus["cases"].as_array().unwrap();
    assert_eq!(cases.len(), 5);
    for case in cases {
        let input = StructuralIr::from_json(&case["input"].to_string()).unwrap();
        let mut graph = Graph::new(input).unwrap();
        summaries::return_and_arguments(&mut graph, &Default::default()).unwrap();
        // This algorithm has no set iteration: even duplicate occurrence order
        // is part of its contract, so compare the full ordered IR directly.
        assert_eq!(
            serde_json::to_value(graph.ir).unwrap(),
            case["result"],
            "{}",
            case["name"]
        );
    }
}
