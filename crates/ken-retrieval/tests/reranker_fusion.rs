use ken_retrieval::reranker_fusion::fused_reranker_order;
use serde::Deserialize;
use serde_json::Value;

#[derive(Deserialize)]
struct Corpus {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    input: Input,
    result: Option<Vec<usize>>,
    error: Option<Value>,
}
#[derive(Deserialize)]
struct Input {
    scores: Vec<Value>,
    weight: Value,
    offset: Value,
}
fn number(value: &Value) -> f64 {
    match value.as_str() {
        Some("nan") => f64::NAN,
        Some("inf") => f64::INFINITY,
        Some("-inf") => f64::NEG_INFINITY,
        None => value.as_f64().expect("original numeric input"),
        _ => panic!("unexpected original numeric tag"),
    }
}
#[test]
fn complete_original_ordinal_fusion_preserves_order_errors_and_membership() {
    let corpus: Corpus =
        serde_json::from_str(include_str!("fixtures/reranker-fusion-reference.json")).unwrap();
    assert_eq!(corpus.cases.len(), 2616);
    for (index, case) in corpus.cases.into_iter().enumerate() {
        let scores: Vec<_> = case.input.scores.iter().map(number).collect();
        let actual = fused_reranker_order(
            &scores,
            number(&case.input.weight),
            number(&case.input.offset),
        );
        match (case.result, case.error) {
            (Some(expected), None) => {
                let order = actual.unwrap_or_else(|error| panic!("case {index}: {error}"));
                assert_eq!(order, expected, "case {index}");
                let mut identities = order;
                identities.sort_unstable();
                assert_eq!(
                    identities,
                    (0..scores.len()).collect::<Vec<_>>(),
                    "case {index}"
                );
            }
            (None, Some(error)) => {
                assert_eq!(error["type"], "ValueError");
                assert_eq!(
                    actual.unwrap_err().to_string(),
                    error["message"].as_str().unwrap(),
                    "case {index}"
                );
            }
            _ => panic!("incomplete original case {index}"),
        }
    }
}
