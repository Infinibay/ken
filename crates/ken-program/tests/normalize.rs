//! The actual caller-visible intermediate tree is compared before bindings mutate it.
use ken_program::{Program, StructuralIr, normalize_syntax};
use serde::Deserialize;
use serde_json::value::RawValue;
#[derive(Deserialize)]
struct Case {
    id: String,
    input: Box<RawValue>,
    prebinding: Option<Program>,
    error: Option<serde_json::Value>,
}
#[derive(Deserialize)]
struct Corpus {
    programs: Vec<Case>,
}
#[test]
fn complete_original_prebinding_trees_scopes_arguments_and_links_match() {
    let corpus: Corpus =
        serde_json::from_str(include_str!("fixtures/program-reference.json")).unwrap();
    assert_eq!(corpus.programs.len(), 90);
    for row in corpus.programs {
        let ir = StructuralIr::from_json(row.input.get()).unwrap();
        let actual = normalize_syntax(&ir);
        if row.error.is_some() {
            assert!(actual.is_err(), "original malformed forest {}", row.id);
        } else {
            assert_eq!(
                actual.unwrap(),
                row.prebinding.unwrap(),
                "{} {}",
                ir.language,
                row.id
            );
        }
    }
}
