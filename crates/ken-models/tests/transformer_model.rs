//! Cold registrations read declared data only and never initialize a tensor core.
use ken_models::{TransformerModel, TransformerSettings};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

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

fn prompted_mean_registration(include_prompt: Option<Value>) -> Value {
    let mut entry = catalog().remove(0);
    let mut pooling = json!({"word_embedding_dimension":1024,"pooling_mode_mean_tokens":true});
    if let Some(value) = include_prompt {
        pooling["include_prompt"] = value;
    }
    for (name, config) in [
        ("1_Pooling/config.json", pooling),
        (
            "config_sentence_transformers.json",
            json!({
                "default_prompt_name":"search","prompts":{"search":"Represent this query: "}
            }),
        ),
    ] {
        let bytes = serde_json::to_vec(&config).unwrap();
        entry["configs"][name] = config;
        entry["assets"]["artifacts"][name] = json!({
            "bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(&bytes))
        });
    }
    entry
}

#[test]
fn authenticated_prompt_exclusion_and_malformed_prompt_policies_are_rejected() {
    for value in [
        json!(false),
        json!(null),
        json!("false"),
        json!(0),
        json!([]),
        json!({}),
    ] {
        let entry = prompted_mean_registration(Some(value.clone()));
        assert!(
            TransformerModel::from_json(&entry.to_string()).is_err(),
            "unsupported include_prompt={value} must fail before inference"
        );
    }
}

#[test]
fn authenticated_prompt_inclusive_mean_pooling_retains_the_original_default() {
    for value in [None, Some(json!(true))] {
        let entry = prompted_mean_registration(value);
        TransformerModel::from_json(&entry.to_string()).unwrap();
    }
}
