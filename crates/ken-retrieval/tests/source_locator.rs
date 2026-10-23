use ken_retrieval::{
    EntityKey,
    source_locator::{SymbolLocator, module_name, symbol_locator},
};
use ken_text::PythonText;
use serde::Deserialize;
use serde_json::value::RawValue;
#[derive(Deserialize)]
struct Fixture {
    families: Families,
}
#[derive(Deserialize)]
struct Families {
    text: Text,
}
#[derive(Deserialize)]
struct Text {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    id: String,
    kind: String,
    input: Box<RawValue>,
    result: Box<RawValue>,
}
#[derive(Deserialize)]
struct Lookup {
    query: PythonText,
    entities: Vec<EntityKey>,
}
#[derive(Deserialize, Debug, PartialEq)]
struct Found {
    locator: Option<SymbolLocator>,
    matches: Vec<bool>,
}
#[derive(Deserialize)]
struct PathInput {
    path: String,
}
#[derive(Deserialize)]
struct TextInput {
    text: PythonText,
}
#[test]
fn complete_locators_module_paths_and_identifiers_match_original() {
    let f: Fixture =
        serde_json::from_str(include_str!("fixtures/search-selection-reference.json")).unwrap();
    let mut counts = [0; 3];
    for c in f.families.text.cases {
        match c.kind.as_str() {
            "locator" => {
                counts[0] += 1;
                let i: Lookup = serde_json::from_str(c.input.get()).unwrap();
                let locator = symbol_locator(&i.query);
                let matches = i
                    .entities
                    .iter()
                    .map(|e| locator.as_ref().is_some_and(|l| l.matches(e)))
                    .collect();
                let actual = Found { locator, matches };
                let expected: Found = serde_json::from_str(c.result.get()).unwrap();
                assert_eq!(actual, expected, "{} {:?}", c.id, i.query);
            }
            "module" => {
                counts[1] += 1;
                let i: PathInput = serde_json::from_str(c.input.get()).unwrap();
                let expected: Option<String> = serde_json::from_str(c.result.get()).unwrap();
                assert_eq!(module_name(&i.path), expected, "{} {}", c.id, i.path);
            }
            "identifier" => {
                counts[2] += 1;
                let i: TextInput = serde_json::from_str(c.input.get()).unwrap();
                let expected: bool = serde_json::from_str(c.result.get()).unwrap();
                assert_eq!(
                    i.text
                        .to_utf8()
                        .is_some_and(|s| ken_text::unicode::identifier(&s)),
                    expected,
                    "{} {:?}",
                    c.id,
                    i.text
                );
            }
            _ => {}
        }
    }
    assert!(counts[0] > 100 && counts[1] > 50 && counts[2] > 10);
}
