use ken_models::{FastEmbedCatalog, FastEmbedModel};
use serde_json::{Value, json};

const CATALOG: &str = include_str!("../resources/fastembed-catalog.json");

fn definition() -> Value {
    serde_json::from_str::<Value>(CATALOG).unwrap()["models"][0].clone()
}

#[test]
fn all_original_models_are_registered_with_distinct_source_identity() {
    let catalog = FastEmbedCatalog::from_json(CATALOG).unwrap();
    assert_eq!(catalog.models().len(), 30);
    let first = catalog.model("BAAI/BGE-BASE-EN").unwrap();
    assert_eq!(first.name(), "BAAI/bge-base-en");
    assert_eq!(first.source_id(), "Qdrant/fast-bge-base-en");
    assert_eq!(first.dim(), 768);
    assert_eq!(
        first.source_revision(),
        "c6080e5aaeee3b64f52aa336e414e74d168ff5a9"
    );
    assert_ne!(first.fingerprint(), first.assets().fingerprint());
    assert_eq!(catalog.models()[1].name(), "BAAI/bge-base-en-v1.5");
    assert!(catalog.model("unknown/model").is_err());
    assert!(catalog.model(" BAAI/bge-base-en").is_err());
    assert_eq!(
        catalog
            .model("snowflaKe/snowflaKe-arctic-embed-xs")
            .unwrap()
            .dim(),
        384
    );
}

#[test]
fn requested_case_alias_keeps_original_prompt_and_notice_spelling() {
    let catalog = FastEmbedCatalog::from_json(CATALOG).unwrap();
    let model = catalog.model("intfloat/multilingual-e5-large").unwrap();
    let alias = model
        .with_requested_name("INTFLOAT/MULTILINGUAL-E5-LARGE")
        .unwrap();
    assert_eq!(alias.name(), "INTFLOAT/MULTILINGUAL-E5-LARGE");
    assert_eq!(alias.assets().fingerprint(), model.assets().fingerprint());
    assert_ne!(alias.fingerprint(), model.fingerprint());
    assert!(
        alias.advisories()[0]
            .message
            .contains("INTFLOAT/MULTILINGUAL-E5-LARGE")
    );
    assert!(model.with_requested_name("different/model").is_err());
}

#[test]
fn invalid_recipes_and_ambiguous_json_are_rejected_before_use() {
    for (field, bad) in [
        ("dimension", json!(0)),
        ("dimension", json!(-1)),
        ("dimension", json!(1.0)),
        ("dimension", json!(true)),
        ("pooling", json!("automatic")),
        ("task_id", json!(0)),
        ("task_id", json!(2)),
        ("task_id", json!(true)),
        ("task_id", json!(1.0)),
        ("format", json!("other")),
        ("graph", json!("../outside")),
        ("source_setup", json!(true)),
    ] {
        let mut model = definition();
        model[field] = bad;
        assert!(
            FastEmbedModel::from_json(&model.to_string()).is_err(),
            "{field}"
        );
    }
    let mut model = definition();
    model["assets"]["artifacts"]
        .as_object_mut()
        .unwrap()
        .remove("config.json");
    assert!(FastEmbedModel::from_json(&model.to_string()).is_err());
    let duplicate = definition().to_string().replacen("\"artifacts\":{", "\"artifacts\":{\"config.json\":{\"bytes\":0,\"sha256\":\"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\"},", 1);
    assert!(FastEmbedModel::from_json(&duplicate).is_err());
    let mut catalog: Value = serde_json::from_str(CATALOG).unwrap();
    let duplicate = catalog["models"][0].clone();
    catalog["models"].as_array_mut().unwrap().push(duplicate);
    assert!(FastEmbedCatalog::from_json(&catalog.to_string()).is_err());
}
