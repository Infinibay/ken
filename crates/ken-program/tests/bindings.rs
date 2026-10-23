//! Public normalized programs and Environment lookups retain independent identity/availability.
use ken_program::{Environment, Program, Resolution, StructuralIr, normalize};
use serde::Deserialize;
use serde_json::value::RawValue;
#[derive(Deserialize)]
struct Lookup {
    name: String,
    scope: i64,
    point: i64,
    result: Option<Resolution>,
    error: Option<serde_json::Value>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    input: Box<RawValue>,
    result: Option<Program>,
    error: Option<serde_json::Value>,
    lookups: Option<Vec<Lookup>>,
}
#[derive(Deserialize)]
struct Corpus {
    programs: Vec<Case>,
}
fn corpus() -> Corpus {
    serde_json::from_str(include_str!("fixtures/program-reference.json")).unwrap()
}
#[test]
fn every_complete_original_program_and_binding_failure_matches() {
    for row in corpus().programs {
        let ir = StructuralIr::from_json(row.input.get()).unwrap();
        let actual = normalize(&ir);
        if row.error.is_some() {
            assert!(actual.is_err(), "lost original failure {}", row.id);
        } else {
            assert_eq!(
                actual.unwrap(),
                row.result.unwrap(),
                "{} {}",
                ir.language,
                row.id
            );
        }
    }
}

#[test]
fn reviewed_annotations_preserve_raw_truthiness_and_original_failures() {
    let corpus: Corpus =
        serde_json::from_str(include_str!("fixtures/program-review.json")).unwrap();
    assert_eq!(corpus.programs.len(), 28);
    for row in corpus.programs {
        let ir = StructuralIr::from_json(row.input.get()).unwrap();
        let actual = normalize(&ir);
        if row.error.is_some() {
            assert!(actual.is_err(), "invalid annotation accepted {}", row.id);
        } else {
            assert_eq!(
                actual.unwrap(),
                row.result.unwrap(),
                "annotation {}",
                row.id
            );
        }
    }
}
#[test]
fn original_lexical_lookups_preserve_status_availability_reason_and_errors() {
    let mut count = 0;
    for row in corpus().programs {
        if row.error.is_some() {
            continue;
        }
        let ir = StructuralIr::from_json(row.input.get()).unwrap();
        let program = normalize(&ir).unwrap();
        let environment = Environment::new(&program);
        for lookup in row.lookups.unwrap() {
            count += 1;
            let actual = environment.resolve(&lookup.name, lookup.scope, lookup.point);
            if lookup.error.is_some() {
                assert!(actual.is_err(), "invalid context accepted {}", row.id);
            } else {
                assert_eq!(
                    actual.unwrap(),
                    lookup.result.unwrap(),
                    "{} lookup{}@{}:{}",
                    row.id,
                    lookup.name,
                    lookup.scope,
                    lookup.point
                );
            }
        }
    }
    assert!(count > 1000, "lost original lookup corpus");
}
