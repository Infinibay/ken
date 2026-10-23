use ken_retrieval::{
    intent::{QueryIntent, interpret, requested_piece_kind, requested_piece_path},
    query::SearchRequest,
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
    result: Option<Box<RawValue>>,
}
#[derive(Deserialize, Debug, PartialEq)]
struct Expected {
    intent: QueryIntent,
    piece_kind: String,
    path: Option<PythonText>,
}
#[test]
fn intent_piece_and_path_authority_match_every_original_text_case() {
    let f: Fixture =
        serde_json::from_str(include_str!("fixtures/search-selection-reference.json")).unwrap();
    let mut count = 0;
    for c in f
        .families
        .text
        .cases
        .into_iter()
        .filter(|c| c.kind == "intent")
    {
        count += 1;
        let request: SearchRequest = serde_json::from_str(c.input.get()).unwrap();
        let expected: Expected = serde_json::from_str(c.result.unwrap().get()).unwrap();
        let actual = Expected {
            intent: interpret(&request),
            piece_kind: requested_piece_kind(&request),
            path: requested_piece_path(&request),
        };
        assert_eq!(actual, expected, "{} query {:?}", c.id, request.query());
    }
    assert!(count > 150);
}
