use ken_native_model_api::{Qwen3Config, TransformerWeightLayout};
#[test]
fn qwen_dimensions_and_parameter_names_have_one_tensor_independent_owner() {
    let config = include_str!("../../../native/ken-torch-backend/tests/fixtures/qwen/config.json");
    let c = Qwen3Config::from_json(config, TransformerWeightLayout::Unprefixed).unwrap();
    assert_eq!(c.layout(), Some(TransformerWeightLayout::Unprefixed));
    assert_eq!(c.parameter_shapes()["embed_tokens.weight"], vec![8, 4]);
    assert_eq!(c.parameter_shapes().len(), 24);
    for (key, value) in [
        ("model_type", serde_json::json!("other")),
        ("head_dim", serde_json::json!(3)),
        ("num_key_value_heads", serde_json::json!(3)),
        ("rope_scaling", serde_json::json!({"type":"linear"})),
        ("attention_bias", serde_json::json!(true)),
    ] {
        let mut bad: serde_json::Value = serde_json::from_str(config).unwrap();
        bad[key] = value;
        assert!(
            Qwen3Config::from_json(&bad.to_string(), TransformerWeightLayout::Unprefixed).is_err()
        );
    }
}
