//! Additional recipes use existing native owners and immutable public selectors.
use ken_models::{
    AcquisitionPolicy, ArtifactCache, CatalogExtensions, EncoderFamily, EncoderSpec,
    LegacyRuntimeIdentity, ModelCatalog, ModelFactory, NativeOnnxRuntime, PreparedModelResources,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
    sync::Arc,
};

fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn declaration(rows: Vec<Value>) -> String {
    json!({"format":"ken-model-catalog-extensions/1","models":rows}).to_string()
}
fn fastembed_row(name: &str) -> Value {
    let mut recipe: Value =
        serde_json::from_str::<Value>(include_str!("../resources/fastembed-catalog.json")).unwrap()
            ["models"][0]
            .clone();
    recipe["name"] = json!(name);
    json!({"backend":"fastembed","recipe":recipe,"prompts":{"query":"","passage":""}})
}
fn transformer_row(name: &str) -> Value {
    let mut recipe =
        serde_json::from_str::<Value>(include_str!("../resources/transformer-catalog.json"))
            .unwrap()["models"][0]
            .clone();
    recipe["name"] = json!(name);
    recipe["assets"]["model_id"] = json!(name);
    json!({"backend":"sentence-transformers","recipe":recipe})
}
fn extended(raw: &str) -> ModelCatalog {
    ModelCatalog::built_in()
        .unwrap()
        .with_extensions(CatalogExtensions::from_json(raw, &hash(raw.as_bytes())).unwrap())
        .unwrap()
}
fn factory(catalog: ModelCatalog, root: &Path) -> ModelFactory {
    ModelFactory::new(
        catalog,
        ArtifactCache::new(&root.join("cache")).unwrap(),
        PreparedModelResources::new(&root.join("private"), &root.join("missing.npz")).unwrap(),
        AcquisitionPolicy::Offline,
    )
}
fn legacy() -> LegacyRuntimeIdentity {
    let value: Value =
        serde_json::from_str(include_str!("fixtures/profile-identity/macos-torch.json")).unwrap();
    LegacyRuntimeIdentity::from_json(&value["legacy_runtime"].to_string()).unwrap()
}

#[test]
fn raw_source_authentication_and_file_boundary_precede_registration() {
    let raw = declaration(vec![fastembed_row("fixture/additional")]);
    let expected = hash(raw.as_bytes());
    let extension = CatalogExtensions::from_json(&raw, &expected).unwrap();
    assert_eq!(extension.identity(), expected);
    assert!(CatalogExtensions::from_json(&raw, &"0".repeat(64)).is_err());
    assert!(CatalogExtensions::from_json("not json", &expected).is_err());
    assert!(CatalogExtensions::from_json(&raw, &expected.to_uppercase()).is_err());
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("catalogue.json");
    fs::write(&path, &raw).unwrap();
    assert_eq!(
        CatalogExtensions::from_file(&path, raw.len() as u64, &expected)
            .unwrap()
            .identity(),
        expected
    );
    assert!(CatalogExtensions::from_file(&path, raw.len() as u64 + 1, &expected).is_err());
    fs::write(&path, format!("{raw} ")).unwrap();
    assert!(CatalogExtensions::from_file(&path, raw.len() as u64, &expected).is_err());
}

#[test]
fn explicit_selector_keeps_additional_onnx_cold_and_preserves_builtin_selection() {
    let temp = tempfile::tempdir().unwrap();
    let raw = declaration(vec![fastembed_row("fixture/additional")]);
    let catalog = extended(&raw);
    let selector = catalog.extension_selector("fixture/additional").unwrap();
    assert!(selector.contains(&hash(raw.as_bytes())));
    assert_ne!(selector, "fixture/additional");
    let listed = catalog.models();
    let descriptor = listed
        .iter()
        .find(|row| row.model == selector)
        .expect("extension must be discoverable with its pinned selector");
    assert_eq!(descriptor.backend, EncoderFamily::FastEmbed);
    assert!(!descriptor.native_inference_accepted);
    let owner = factory(catalog, temp.path());
    assert!(
        owner.legacy_encoder("fixture/additional").is_err(),
        "bare aliases would silently change existing project vectors"
    );
    let encoder = owner.legacy_encoder(&selector).unwrap();
    assert_eq!(encoder.family(), EncoderFamily::FastEmbed);
    assert!(Arc::ptr_eq(
        &encoder,
        &owner.legacy_encoder(&selector).unwrap()
    ));
    assert_eq!(encoder.dim().unwrap(), 768);
    assert!(encoder.embed_passages(&[]).unwrap().is_empty());
    assert!(encoder.preparation().unwrap().is_none());
    assert!(
        encoder.embed_query("hello").is_err(),
        "no optional runtime may be silently substituted"
    );
    assert_eq!(
        owner.legacy_encoder("BAAI/bge-base-en").unwrap().family(),
        EncoderFamily::FastEmbed
    );
    assert!(!temp.path().join("private").exists());
}

#[test]
fn every_catalogue_byte_and_recipe_change_invalidates_old_selectors() {
    let base = declaration(vec![fastembed_row("fixture/additional")]);
    let original = extended(&base)
        .extension_selector("fixture/additional")
        .unwrap();
    let mut recipe_changed = fastembed_row("fixture/additional");
    recipe_changed["recipe"]["pooling"] = json!("mean");
    let mut asset_changed = fastembed_row("fixture/additional");
    asset_changed["recipe"]["assets"]["revision"] = json!("a".repeat(40));
    for raw in [
        format!("{base}\n"),
        declaration(vec![recipe_changed]),
        declaration(vec![asset_changed]),
    ] {
        let catalog = extended(&raw);
        let selected = catalog.extension_selector("fixture/additional").unwrap();
        assert_ne!(original, selected);
        let temp = tempfile::tempdir().unwrap();
        assert!(
            factory(catalog, temp.path())
                .legacy_encoder(&original)
                .is_err()
        );
    }
}

#[test]
fn builtin_names_case_aliases_and_cross_family_conflicts_cannot_be_shadowed() {
    for name in [
        "BAAI/BGE-BASE-EN",
        "minishlab/potion-code-16M-v2",
        "Qwen/Qwen3-Embedding-0.6B",
        "Qwen/Qwen3-Reranker-0.6B",
        "ken/static-qwen3-r512-v2",
    ] {
        let raw = declaration(vec![fastembed_row(name)]);
        let result = CatalogExtensions::from_json(&raw, &hash(raw.as_bytes()))
            .and_then(|extension| ModelCatalog::built_in().unwrap().with_extensions(extension));
        assert!(result.is_err(), "{name}");
    }
    for rows in [
        vec![
            fastembed_row("fixture/model"),
            fastembed_row("FIXTURE/MODEL"),
        ],
        vec![
            fastembed_row("fixture/model"),
            transformer_row("fixture/model"),
        ],
    ] {
        let raw = declaration(rows);
        assert!(CatalogExtensions::from_json(&raw, &hash(raw.as_bytes())).is_err());
    }
}

#[test]
fn unsupported_policies_fields_and_ambiguous_objects_are_rejected() {
    let mut rows = Vec::new();
    for (pointer, value) in [
        ("/recipe/pooling", json!("automatic")),
        ("/recipe/graph", json!("../outside")),
        ("/prompts/query", json!("query: ")),
        ("/prompts/passage", json!("passage: ")),
        ("/recipe/assets/revision", json!("main")),
        ("/recipe/dimension", json!(0)),
        (
            "/recipe/assets/artifacts/config.json/bytes",
            json!(u64::MAX),
        ),
    ] {
        let mut row = fastembed_row("fixture/additional");
        *row.pointer_mut(pointer).unwrap() = value;
        rows.push(row);
    }
    let mut unexpected = fastembed_row("fixture/additional");
    unexpected["qualified"] = json!(true);
    rows.push(unexpected);
    let mut missing = fastembed_row("fixture/additional");
    missing.as_object_mut().unwrap().remove("prompts");
    rows.push(missing);
    for row in rows {
        let raw = declaration(vec![row]);
        assert!(
            CatalogExtensions::from_json(&raw, &hash(raw.as_bytes())).is_err(),
            "{raw}"
        );
    }
    let raw = declaration(vec![fastembed_row("fixture/additional")]);
    let duplicate = raw.replacen("\"dimension\":768", "\"dimension\":2,\"dimension\":768", 1);
    assert_ne!(raw, duplicate);
    assert!(CatalogExtensions::from_json(&duplicate, &hash(duplicate.as_bytes())).is_err());
    for raw in [
        json!({"format":"other","models":[]}).to_string(),
        declaration(vec![]),
    ] {
        assert!(CatalogExtensions::from_json(&raw, &hash(raw.as_bytes())).is_err());
    }
}

#[test]
fn supported_transformer_profiles_bind_catalogue_identity_without_widening_original_families() {
    let raw = declaration(vec![transformer_row("fixture/xlm-encoder")]);
    let catalog = extended(&raw);
    let spec = catalog.extension_spec("fixture/xlm-encoder").unwrap();
    assert_eq!(
        serde_json::to_value(&spec).unwrap()["backend"],
        "sentence-transformers"
    );
    assert_eq!(spec.revision.len(), 64);
    let raw_new = format!("{raw} ");
    let changed = extended(&raw_new)
        .extension_spec("fixture/xlm-encoder")
        .unwrap();
    assert_ne!(spec.revision, changed.revision);
    let temp = tempfile::tempdir().unwrap();
    let owner = factory(catalog, temp.path());
    let encoder = owner.encoder(&spec, &legacy()).unwrap();
    assert_eq!(encoder.family(), EncoderFamily::SentenceTransformer);
    assert!(encoder.preparation().unwrap().is_none());
    assert!(owner.encoder(&changed, &legacy()).is_err());
    let mut upstream = spec.clone();
    upstream.revision = "a".repeat(40);
    assert!(owner.encoder(&upstream, &legacy()).is_err());
    let onnx = extended(&declaration(vec![fastembed_row("fixture/onnx")]));
    assert!(
        onnx.extension_spec("fixture/onnx").is_err(),
        "ONNX must not masquerade as an original profile family"
    );
    assert!(
        EncoderSpec::from_json(
            &json!({"model_id":"fixture/onnx","revision":"a".repeat(64),"backend":"fastembed"})
                .to_string()
        )
        .is_err()
    );
}

#[test]
fn unsupported_transformer_architectures_module_sequences_and_judge_roles_stay_rejected() {
    for (pointer, value) in [
        ("/recipe/architecture", json!("bert")),
        ("/recipe/role", json!("judge")),
        (
            "/recipe/configs/modules.json/0/type",
            json!("remote.CustomPython"),
        ),
        (
            "/recipe/configs/1_Pooling~1config.json/include_prompt",
            json!(false),
        ),
    ] {
        let mut row = transformer_row("fixture/additional");
        if let Some(destination) = row.pointer_mut(pointer) {
            *destination = value;
        } else {
            row["recipe"]["configs"]["1_Pooling/config.json"]["include_prompt"] = value;
        }
        let raw = declaration(vec![row]);
        assert!(
            CatalogExtensions::from_json(&raw, &hash(raw.as_bytes())).is_err(),
            "{pointer}"
        );
    }
}

struct OnnxFixture {
    _temp: tempfile::TempDir,
    root: PathBuf,
    snapshot: PathBuf,
    row: Value,
}
impl OnnxFixture {
    fn new() -> Self {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().to_path_buf();
        let snapshot = root.join("1111111111111111111111111111111111111111");
        fs::create_dir(&snapshot).unwrap();
        let tokenizer=json!({"version":"1.0","truncation":null,"padding":null,"added_tokens":[],"normalizer":null,"pre_tokenizer":{"type":"Whitespace"},"post_processor":null,"decoder":null,"model":{"type":"WordLevel","vocab":{"[UNK]":0,"[PAD]":1,"a":2,"b":3},"unk_token":"[UNK]"}}).to_string();
        let mut artifacts = serde_json::Map::new();
        let graph = fs::read(
            Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/fastembed/hidden.onnx"),
        )
        .unwrap();
        for (name, bytes) in [
            ("model.onnx", graph.as_slice()),
            ("tokenizer.json", tokenizer.as_bytes()),
            ("config.json", b"{\"pad_token_id\":1}"),
            (
                "tokenizer_config.json",
                b"{\"max_length\":8,\"pad_token\":\"[PAD]\"}",
            ),
            ("special_tokens_map.json", b"{}"),
        ] {
            fs::write(snapshot.join(name), bytes).unwrap();
            artifacts.insert(
                name.into(),
                json!({"bytes":bytes.len(),"sha256":hash(bytes)}),
            );
        }
        let row = json!({"backend":"fastembed","prompts":{"query":"","passage":""},"recipe":{"format":"ken-fastembed-model/1","name":"fixture/native-onnx","assets":{"model_id":"fixture/native-onnx","revision":"1111111111111111111111111111111111111111","artifacts":artifacts},"graph":"model.onnx","dimension":2,"pooling":"mean","advisories":[]}});
        Self {
            _temp: temp,
            root,
            snapshot,
            row,
        }
    }
}

#[test]
fn registration_asset_availability_and_numerical_acceptance_are_distinct_facts() {
    let fixture = OnnxFixture::new();
    let raw = declaration(vec![fixture.row.clone()]);
    let catalog = extended(&raw);
    let selector = catalog.extension_selector("fixture/native-onnx").unwrap();
    let cold = serde_json::to_value(catalog.extension_status(&selector, None).unwrap()).unwrap();
    assert_eq!(cold["registered"], true);
    assert_eq!(cold["resources"], "not_checked");
    assert_eq!(cold["native_inference_accepted"], false);
    let verified = serde_json::to_value(
        catalog
            .extension_status(&selector, Some(&fixture.snapshot))
            .unwrap(),
    )
    .unwrap();
    assert_eq!(verified["resources"], "verified");
    assert_eq!(verified["native_inference_accepted"], false);
    fs::write(fixture.snapshot.join("model.onnx"), b"tampered").unwrap();
    assert!(
        catalog
            .extension_status(&selector, Some(&fixture.snapshot))
            .is_err()
    );
    assert!(
        catalog
            .extension_status(&selector, Some(&fixture.root.join("missing")))
            .is_err()
    );
    assert!(
        catalog
            .extension_status("fixture/native-onnx", None)
            .is_err()
    );
}

#[test]
fn additional_onnx_recipe_reaches_real_native_query_and_passage_execution() {
    let fixture = OnnxFixture::new();
    let raw = declaration(vec![fixture.row.clone()]);
    let catalog = extended(&raw);
    let selector = catalog.extension_selector("fixture/native-onnx").unwrap();
    let mut resources = PreparedModelResources::new(
        &fixture.root.join("private"),
        &fixture.root.join("absent.npz"),
    )
    .unwrap();
    resources
        .source_overrides
        .insert("fixture/native-onnx".into(), fixture.snapshot.clone());
    let runtime = NativeOnnxRuntime::from_json(
        include_str!("../resources/onnx-runtime-libraries.json"),
        &PathBuf::from(
            std::env::var_os("KEN_ORT_LIBRARY").expect("explicit prepared KEN_ORT_LIBRARY"),
        ),
    )
    .unwrap();
    resources.onnx = Some(runtime.clone());
    let owner = ModelFactory::new(
        catalog,
        ArtifactCache::new(&fixture.root.join("cache")).unwrap(),
        resources,
        AcquisitionPolicy::Offline,
    );
    let encoder = owner.legacy_encoder(&selector).unwrap();
    assert!(!encoder.is_prepared().unwrap());
    assert!(runtime.loaded_identity().unwrap().is_none());
    assert_eq!(encoder.embed_query("a").unwrap(), vec![2., 2.]);
    assert_eq!(
        encoder.embed_passages(&["b", "a b"]).unwrap(),
        vec![vec![3., 3.], vec![2.5, 2.5]]
    );
    assert!(encoder.is_prepared().unwrap());
    assert!(runtime.loaded_identity().unwrap().is_some());
}
