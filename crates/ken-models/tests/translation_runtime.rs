#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
use ken_models::{LocalQueryExpansion, NativeTranslationRuntime, TranslationModel};
use serde_json::{Value, json};
use std::{fs, path::PathBuf};

fn registration() -> Value {
    let core: Value =
        serde_json::from_str(include_str!("../resources/ct2-runtime-libraries.json")).unwrap();
    let row = &core["runtimes"][0];
    json!({"format":"ken-native-translation/1","runtimes":[{
        "os":row["os"],"arch":row["arch"],"core_version":row["version"],"abi":1,
        "module":{"bytes":1,"sha256":"0".repeat(64)},"libraries":row["libraries"]}]})
}

fn prepared() -> (String, PathBuf, PathBuf) {
    let path = PathBuf::from(
        std::env::var_os("KEN_CT2_PREPARATION")
            .expect("prepare the explicit native CT2 CPU backend"),
    );
    let value: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
    (
        value["registration"].to_string(),
        value["module_path"].as_str().unwrap().into(),
        value["core_root"].as_str().unwrap().into(),
    )
}

#[test]
fn parsing_a_translation_runtime_and_english_remain_cold() {
    let temp = tempfile::tempdir().unwrap();
    let module = temp.path().join("absent-module.so");
    let core = temp.path().join("absent-core");
    let runtime =
        NativeTranslationRuntime::from_json(&registration().to_string(), &module, &core).unwrap();
    assert!(runtime.loaded_identity().unwrap().is_none());
    let model = TranslationModel::from_json(include_str!(
        "../../../src/ken/embedder/data/es-en-ct2-int8.json"
    ))
    .unwrap();
    let cache = temp.path().join("absent-cache");
    let engine = LocalQueryExpansion::new(model, None, cache.clone())
        .unwrap()
        .with_native_runtime(runtime.clone());
    assert_eq!(
        engine.expand("find the input parser").unwrap(),
        "find the input parser"
    );
    assert!(!engine.is_loaded() && runtime.loaded_identity().unwrap().is_none());
    assert!(!module.exists() && !core.exists() && !cache.exists());
}

#[test]
fn foreign_core_architecture_and_abi_are_rejected_before_loading() {
    for change in ["architecture", "core", "abi"] {
        let mut value = registration();
        let row = &mut value["runtimes"][0];
        match change {
            "architecture" => row["arch"] = json!("aarch64"),
            "core" => {
                row["libraries"]
                    .as_object_mut()
                    .unwrap()
                    .values_mut()
                    .next()
                    .unwrap()["sha256"] = json!("0".repeat(64))
            }
            _ => row["abi"] = json!(2),
        }
        assert!(
            NativeTranslationRuntime::from_json(
                &value.to_string(),
                &PathBuf::from("/absent/module"),
                &PathBuf::from("/absent/core")
            )
            .is_err(),
            "{change}"
        );
    }
}

#[test]
fn actual_runtime_load_is_retryable_and_clones_share_the_owned_module() {
    let (registration, source, core) = prepared();
    let temp = tempfile::tempdir().unwrap();
    let alias = temp.path().join("module.so");
    let runtime = NativeTranslationRuntime::from_json(&registration, &alias, &core).unwrap();
    assert!(runtime.load().is_err());
    assert!(runtime.loaded_identity().unwrap().is_none());
    fs::copy(source, &alias).unwrap();
    let identity = runtime.load().unwrap();
    assert_eq!(identity.core_version, "4.8.2");
    assert!(matches!(identity.int8_backend.as_str(), "MKL" | "DNNL"));
    assert_eq!(identity.float_backend, identity.int8_backend);
    assert_eq!(runtime.clone().load().unwrap(), identity);
}

#[test]
fn every_new_alias_is_verified_even_when_an_identical_runtime_is_live() {
    let (registration, source, core) = prepared();
    let temp = tempfile::tempdir().unwrap();
    let alias = temp.path().join("module.so");
    fs::copy(source, &alias).unwrap();
    let first = NativeTranslationRuntime::from_json(&registration, &alias, &core).unwrap();
    let identity = first.load().unwrap();
    fs::write(&alias, b"changed source module").unwrap();
    assert_eq!(
        first.load().unwrap(),
        identity,
        "active private code survives source replacement"
    );
    let fresh = NativeTranslationRuntime::from_json(&registration, &alias, &core).unwrap();
    assert!(
        fresh.load().is_err(),
        "an identical descriptor cannot authenticate a changed alias"
    );
}

#[test]
fn changing_the_explicit_runtime_invalidates_an_already_loaded_session() {
    let (value, module, core) = prepared();
    let good = NativeTranslationRuntime::from_json(&value, &module, &core).unwrap();
    let root = tempfile::tempdir().unwrap();
    let model = TranslationModel::from_json(include_str!(
        "../../../src/ken/embedder/data/es-en-ct2-int8.json"
    ))
    .unwrap();
    let source = std::env::var_os("KEN_TRANSLATION_SOURCE").unwrap().into();
    let engine = LocalQueryExpansion::new(
        model,
        Some(source),
        root.path().join("c96e2c5399ebfae4fc43d9669556b9afa74bb69d"),
    )
    .unwrap()
    .with_native_runtime(good);
    engine.load().unwrap();
    assert!(engine.is_loaded());
    let replacement = NativeTranslationRuntime::from_json(
        &registration().to_string(),
        &root.path().join("absent-module"),
        &core,
    )
    .unwrap();
    let engine = engine.with_native_runtime(replacement);
    assert!(
        !engine.is_loaded(),
        "the previous session must not mask the new declaration"
    );
    assert_eq!(engine.expand("find the parser").unwrap(), "find the parser");
    assert!(engine.expand("¿Dónde está la función?").is_err());
    assert!(!engine.is_loaded());
}
