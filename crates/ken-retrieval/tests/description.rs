use ken_retrieval::{
    Passage,
    description::{OwnerDescription, describe_owner},
};
use serde::Deserialize;
use serde_json::{Value, value::RawValue};
#[derive(Deserialize)]
struct Fixture {
    families: Families,
}
#[derive(Deserialize)]
struct Families {
    owners: Family,
}
#[derive(Deserialize)]
struct Family {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    input: Box<RawValue>,
    result: Option<Box<RawValue>>,
    error: Option<Value>,
}
#[derive(Deserialize)]
struct Input {
    passages: Vec<Passage>,
}
#[test]
fn complete_owned_descriptions_match_original_without_filling_foreign_source_gaps() {
    let f: Fixture =
        serde_json::from_str(include_str!("fixtures/search-selection-reference.json")).unwrap();
    assert_eq!(f.families.owners.cases.len(), 83);
    for c in f.families.owners.cases {
        let i: Input = serde_json::from_str(c.input.get()).unwrap();
        let actual = describe_owner(&i.passages);
        if let Some(error) = c.error {
            assert!(
                actual
                    .unwrap_err()
                    .to_string()
                    .contains(error["message"].as_str().unwrap()),
                "{}",
                c.id
            );
        } else {
            let expected: OwnerDescription = serde_json::from_str(c.result.unwrap().get()).unwrap();
            assert_eq!(actual.unwrap(), expected, "{}", c.id);
        }
    }
}
