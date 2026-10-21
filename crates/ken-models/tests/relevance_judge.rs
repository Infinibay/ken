use ken_models::{JudgeTokens, ModelFileSource, TransformerModel};
use serde_json::Value;
use std::path::PathBuf;
#[test]
fn all_original_purposes_query_limits_budgets_empty_errors_and_order_match() {
    let golden: Value =
        serde_json::from_str(include_str!("fixtures/judge-tokens/original.json")).unwrap();
    let catalog: Value =
        serde_json::from_str(include_str!("../resources/transformer-catalog.json")).unwrap();
    let declaration = &catalog["models"]
        .as_array()
        .unwrap()
        .iter()
        .find(|m| m["name"] == golden["model"])
        .unwrap();
    let model = TransformerModel::from_json(&declaration.to_string()).unwrap();
    let sources = PathBuf::from(
        std::env::var_os("KEN_TRANSFORMER_SOURCE_ROOT").expect("prepare registered source"),
    );
    let source = ModelFileSource::new(
        &sources
            .join(
                declaration["assets"]["model_id"]
                    .as_str()
                    .unwrap()
                    .replace('/', "--"),
            )
            .join(declaration["assets"]["revision"].as_str().unwrap()),
        &sources,
    )
    .unwrap();
    let tokens = JudgeTokens::load(&model, &source).unwrap();
    for case in golden["cases"].as_array().unwrap() {
        let request = &case["request"];
        let documents: Vec<_> = request["documents"]
            .as_array()
            .unwrap()
            .iter()
            .map(|d| d.as_str().unwrap())
            .collect();
        let actual = tokens.prepare(
            request["query"].as_str().unwrap(),
            &documents,
            request["purpose"].as_str().unwrap(),
            request["sequence_length"].as_u64().unwrap() as usize,
            16,
        );
        if let Some(kind) = case["exception"].as_str() {
            assert_eq!(
                actual.err().unwrap().original_kind(),
                kind,
                "{}",
                request["id"]
            );
        } else {
            let actual = actual.unwrap();
            assert_eq!(
                actual.remaining,
                request["remaining"].as_u64().unwrap() as usize
            );
            assert_eq!(
                serde_json::to_value(actual.query_ids).unwrap(),
                request["query_ids"]
            );
            assert_eq!(
                serde_json::to_value(actual.batches).unwrap(),
                case["feeds"],
                "{}",
                request["id"]
            );
            assert_eq!(
                serde_json::to_value(actual.projection_ids).unwrap(),
                case["projection_ids"]
            );
        }
    }
}
