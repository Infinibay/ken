//! Public catalogue metadata is independent of native recipe/inference status.
use ken_maintenance::{ConfigEnvironment, UserConfig, models};
use ken_models::{CatalogExtensions, ModelCatalog};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
fn config(root: &std::path::Path) -> UserConfig {
    UserConfig::new(&ConfigEnvironment {
        config_dir: Some(root.join("config")),
        xdg_config_home: None,
        home: root.into(),
    })
}
fn original() -> Value {
    let raw = include_bytes!("fixtures/public-model-metadata.json");
    assert_eq!(raw.len(), 5064);
    assert_eq!(
        format!("{:x}", Sha256::digest(raw)),
        "30d7cbb0cd839ab648373711ce722b8ba0269a10b1ce925063d59a24591264c5"
    );
    serde_json::from_slice(raw).unwrap()
}
fn public(row: &Value) -> Value {
    json!({"model":row["model"],"dim":row["dim"],"mb":row["mb"],"multilingual":row["multilingual"],"backend":row["backend"]})
}
#[test]
fn every_original_public_row_keeps_its_exact_metadata_and_sorted_order() {
    let d = tempfile::tempdir().unwrap();
    let result = models(&config(d.path()), &ModelCatalog::built_in().unwrap()).unwrap();
    let f = original();
    let expected = f["models"].as_array().unwrap();
    assert_eq!(expected.len(), 32);
    assert_eq!(
        result["models"].as_array().unwrap()[..32]
            .iter()
            .map(public)
            .collect::<Vec<_>>(),
        *expected
    );
    assert!(result["unsupported_models"].as_array().unwrap().is_empty());
    for row in result["models"].as_array().unwrap() {
        assert_eq!(row["registered"], true);
        assert!(row["registration"].is_object());
        assert_eq!(row["native_inference_accepted"], false);
    }
    assert!(!d.path().join("config").exists());
    assert!(!d.path().join("cache").exists());
    assert!(!d.path().join("private").exists());
}
#[test]
fn advertised_mb_is_not_replaced_by_native_artifact_bytes_and_defaults_stay_prospective() {
    let d = tempfile::tempdir().unwrap();
    let c = config(d.path());
    c.set_default_model(Some("prospective/user-choice"))
        .unwrap();
    let result = models(&c, &ModelCatalog::built_in().unwrap()).unwrap();
    assert_eq!(result["default"], "prospective/user-choice");
    let row = result["models"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["model"] == "BAAI/bge-base-en")
        .unwrap();
    let expected = original()["models"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["model"] == "BAAI/bge-base-en")
        .unwrap()
        .clone();
    assert_eq!(public(row), expected);
    assert_eq!(row["native_backend"], "fast_embed");
    assert_eq!(row["bytes"], 436314078u64);
    assert_ne!(
        row["mb"].as_f64().unwrap(),
        row["bytes"].as_f64().unwrap() / 1000000.
    );
}
#[test]
fn native_only_models_have_explicit_unknown_public_metadata() {
    let d = tempfile::tempdir().unwrap();
    let result = models(&config(d.path()), &ModelCatalog::built_in().unwrap()).unwrap();
    for name in ["ken/static-qwen3-r512-v2", "minishlab/potion-code-16M-v2"] {
        let row = result["models"]
            .as_array()
            .unwrap()
            .iter()
            .find(|r| r["model"] == name)
            .unwrap();
        assert!(row["multilingual"].is_null());
        assert!(row["mb"].is_null());
        assert_eq!(row["metadata_source"], "native_registration");
        assert_eq!(row["registered"], true);
        assert!(row["bytes"].as_u64().unwrap() > 0);
    }
}
#[test]
fn extensions_never_infer_multilingual_or_advertised_size_from_their_name() {
    let mut recipe: Value = serde_json::from_str::<Value>(include_str!(
        "../../ken-models/resources/fastembed-catalog.json"
    ))
    .unwrap()["models"][0]
        .clone();
    recipe["name"] = json!("fixture/multilingual-unknown");
    let declaration=json!({"format":"ken-model-catalog-extensions/1","models":[{"backend":"fastembed","recipe":recipe,"prompts":{"query":"","passage":""}}]}).to_string();
    let extension = CatalogExtensions::from_json(
        &declaration,
        &format!("{:x}", Sha256::digest(declaration.as_bytes())),
    )
    .unwrap();
    let catalog = ModelCatalog::built_in()
        .unwrap()
        .with_extensions(extension)
        .unwrap();
    let selector = catalog
        .extension_selector("fixture/multilingual-unknown")
        .unwrap();
    let d = tempfile::tempdir().unwrap();
    let result = models(&config(d.path()), &catalog).unwrap();
    let row = result["models"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["model"] == selector)
        .unwrap();
    assert!(row["multilingual"].is_null());
    assert!(row["mb"].is_null());
    assert_eq!(row["backend"], "fastembed");
    assert_eq!(row["native_backend"], "fast_embed");
    assert_eq!(row["registered"], true);
    assert_eq!(row["native_inference_accepted"], false);
    assert!(row["registration"]["revision"].is_string());
    assert!(!d.path().join("cache").exists());
}
