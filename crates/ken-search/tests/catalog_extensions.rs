//! Both focused and lazy search factories use the same captured catalogue.
use ken_models::EncoderFamily;
use ken_search::SearchInstallation;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
};
fn declaration(root: &Path, grammar: Option<PathBuf>) -> (PathBuf, String) {
    let mut row = serde_json::from_str::<Value>(include_str!(
        "../../ken-models/resources/fastembed-catalog.json"
    ))
    .unwrap()["models"][0]
        .clone();
    row["name"] = json!("fixture/search-extension");
    let raw=json!({"format":"ken-model-catalog-extensions/1","models":[{"backend":"fastembed","recipe":row,"prompts":{"query":"","passage":""}}]}).to_string();
    let digest = format!("{:x}", Sha256::digest(raw.as_bytes()));
    fs::write(root.join("catalogue.json"), &raw).unwrap();
    let legacy = serde_json::from_str::<Value>(include_str!(
        "../../ken-models/tests/fixtures/profile-identity/linux.json"
    ))
    .unwrap()["legacy_runtime"]
        .clone();
    let path = root.join("search.json");
    fs::write(&path,json!({"format":"ken-search-installation/1","grammar_manifest":grammar.unwrap_or(root.join("missing-grammar")),"ranking_directory":"missing-ranks","private_parent":"private","cache_parent":"cache","bundled_npz":"absent.npz","sources":{},"acquisition":"offline","legacy_runtime":legacy,"onnx_library":null,"translation":null,"catalogue_extensions":{"path":"catalogue.json","bytes":raw.len(),"sha256":digest}}).to_string()).unwrap();
    (
        path,
        format!("ken-catalogue:{digest}:fixture/search-extension"),
    )
}
#[test]
fn metadata_and_focused_factory_consume_authenticated_declaration_without_optional_resources() {
    let temp = tempfile::tempdir().unwrap();
    let (path, selector) = declaration(temp.path(), None);
    let catalog = SearchInstallation::model_catalog(&path).unwrap();
    assert_eq!(
        catalog
            .extension_selector("fixture/search-extension")
            .unwrap(),
        selector
    );
    let factory = SearchInstallation::open_model_factory(&path).unwrap();
    let encoder = factory.legacy_encoder(&selector).unwrap();
    assert_eq!(encoder.family(), EncoderFamily::FastEmbed);
    assert_eq!(encoder.dim().unwrap(), 768);
    assert!(encoder.preparation().unwrap().is_none());
    assert!(!temp.path().join("private").exists());
    assert!(!temp.path().join("missing-grammar").exists());
    fs::write(
        temp.path().join("catalogue.json"),
        "changed authenticated source",
    )
    .unwrap();
    assert!(SearchInstallation::model_catalog(&path).is_err());
    assert!(SearchInstallation::open_model_factory(&path).is_err());
}
#[test]
fn lazy_full_factory_retains_its_opened_catalogue_instead_of_rereading_mutable_source() {
    let temp = tempfile::tempdir().unwrap();
    let (path, selector) = declaration(
        temp.path(),
        Some(PathBuf::from(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").expect("prepared grammar declaration"),
        )),
    );
    let installed = SearchInstallation::open(&path).unwrap();
    fs::write(
        temp.path().join("catalogue.json"),
        "changed after declaration capture",
    )
    .unwrap();
    let factory = installed.model_factory().unwrap();
    assert_eq!(
        factory.legacy_encoder(&selector).unwrap().family(),
        EncoderFamily::FastEmbed
    );
    assert!(SearchInstallation::model_catalog(&path).is_err());
    assert!(!temp.path().join("private").exists());
}
