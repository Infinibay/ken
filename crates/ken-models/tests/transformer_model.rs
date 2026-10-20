//! Cold registrations read declared data only and never initialize a tensor core.
use ken_models::{TransformerModel, TransformerSettings};
use serde_json::Value;

fn catalog() -> Vec<Value> {
    serde_json::from_str::<Value>(include_str!("../resources/transformer-catalog.json"))
        .unwrap()["models"].as_array().unwrap().clone()
}

#[test]
fn original_registrations_have_exact_architecture_weights_and_pooling_without_files() {
    let entries = catalog();
    assert_eq!(entries.len(), 3);
    for entry in entries {
        let model = TransformerModel::from_json(&entry.to_string()).unwrap();
        assert_eq!(
            serde_json::to_value(model.assets()).unwrap()["model_id"],
            entry["name"]
        );
        assert_eq!(model.dimension(), 1024);
        assert_eq!(
            model.vocabulary(),
            entry["configs"]["config.json"]["vocab_size"]
                .as_u64()
                .unwrap()
        );
        assert!(!model.weight_files().is_empty());
        assert!(
            model
                .weight_files()
                .iter()
                .all(|name| entry["assets"]["artifacts"].get(name).is_some())
        );
        if entry["role"] == "encoder" {
            assert_eq!(model.normalize_modules(), 1);
        } else {
            assert_eq!(model.normalize_modules(), 0);
        }
    }
}

#[test]
fn invalid_or_unregistered_transformer_configuration_is_rejected() {
    let base = catalog().remove(0);
    for (pointer, value) in [
        ("/name", serde_json::json!("pretended/alias")),
        ("/dimension", serde_json::json!(3)),
        ("/architecture", serde_json::json!("unknown")),
        (
            "/configs/modules.json/0/type",
            serde_json::json!("untrusted.models.Transformer"),
        ),
        (
            "/configs/config.json/model_type",
            serde_json::json!("qwen3"),
        ),
        (
            "/configs/1_Pooling~1config.json/pooling_mode_max_tokens",
            serde_json::json!(true),
        ),
        ("/configs/config.json/vocab_size", serde_json::json!(0)),
    ] {
        let mut entry = base.clone();
        *entry.pointer_mut(pointer).unwrap() = value;
        assert!(
            TransformerModel::from_json(&entry.to_string()).is_err(),
            "{pointer}"
        );
    }
}

#[test]
fn unset_dtype_means_original_float32_and_zero_limits_are_errors() {
    let settings = TransformerSettings::default();
    assert_eq!(
        serde_json::to_value(settings.effective_dtype()).unwrap(),
        "float32"
    );
    settings.validate().unwrap();
    assert!(
        TransformerSettings {
            sequence_length: Some(0),
            ..settings.clone()
        }
        .validate()
        .is_err()
    );
    assert!(
        TransformerSettings {
            batch_size: Some(0),
            ..settings
        }
        .validate()
        .is_err()
    );
}
