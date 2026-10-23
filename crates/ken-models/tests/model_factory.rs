//! A caller selects a compatible profile, without opening optional runtimes.
use ken_models::{
    AcquisitionPolicy, ArtifactCache, EncoderFamily, EncoderSpec, LegacyRuntimeIdentity,
    ModelCatalog, ModelFactory, PreparedModelResources,
};
use serde_json::{Value, json};
use std::{path::Path, sync::Arc};

fn original_runtime() -> LegacyRuntimeIdentity {
    let capture: Value =
        serde_json::from_str(include_str!("fixtures/profile-identity/macos.json")).unwrap();
    LegacyRuntimeIdentity::from_json(&capture["legacy_runtime"].to_string()).unwrap()
}

fn cold_factory(root: &Path) -> ModelFactory {
    let resources =
        PreparedModelResources::new(&root.join("owned"), &root.join("absent.npz")).unwrap();
    ModelFactory::new(
        ModelCatalog::built_in().unwrap(),
        ArtifactCache::new(&root.join("cache")).unwrap(),
        resources,
        AcquisitionPolicy::Offline,
    )
}

#[test]
fn cold_registered_profiles_require_neither_sources_nor_optional_sdks() {
    let temp = tempfile::tempdir().unwrap();
    let catalog = ModelCatalog::built_in().unwrap();
    let factory = cold_factory(temp.path());
    for (spec, family) in [
        (catalog.static_spec(), EncoderFamily::StaticTable),
        (catalog.potion_spec(), EncoderFamily::Potion),
    ] {
        let encoder = factory.encoder(&spec, &original_runtime()).unwrap();
        assert_eq!(encoder.family(), family);
        assert!(!encoder.is_prepared().unwrap());
        let preparation: Option<ken_models::EncoderPreparation> = encoder.preparation().unwrap();
        assert!(preparation.is_none());
        assert!(encoder.embed_passages(&[]).unwrap().is_empty());
        assert!(!encoder.is_prepared().unwrap());
    }
    assert!(!temp.path().join("owned").exists());
    assert!(!temp.path().join("absent.npz").exists());
}

#[test]
fn every_registered_legacy_name_selects_its_family_and_never_the_judge() {
    let temp = tempfile::tempdir().unwrap();
    let factory = cold_factory(temp.path());
    let catalog: Value =
        serde_json::from_str(include_str!("../resources/fastembed-catalog.json")).unwrap();
    for model in catalog["models"].as_array().unwrap() {
        let encoder = factory
            .legacy_encoder(model["name"].as_str().unwrap())
            .unwrap();
        assert_eq!(encoder.family(), EncoderFamily::FastEmbed);
        assert!(!encoder.is_prepared().unwrap());
    }
    assert_eq!(
        factory
            .legacy_encoder("Qwen/Qwen3-Embedding-0.6B")
            .unwrap()
            .family(),
        EncoderFamily::SentenceTransformer
    );
    assert!(factory.legacy_encoder("Qwen/Qwen3-Reranker-0.6B").is_err());
    assert!(factory.legacy_encoder("unknown/model").is_err());
}

#[test]
fn original_potion_profile_fingerprint_is_distinct_from_its_upstream_commit() {
    let catalog = ModelCatalog::built_in().unwrap();
    let spec = catalog.potion_spec();
    // Captured from the original potion_profile(), not a Rust-derived expected hash.
    assert_eq!(
        spec.revision,
        "358803c97ebfa214e3cc325cfb1c8d0e4ceaf38d060676a7c2e40f9204c1589e"
    );
    let temp = tempfile::tempdir().unwrap();
    let factory = cold_factory(temp.path());
    let mut wrong = serde_json::to_value(&spec).unwrap();
    wrong["revision"] = json!("e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b");
    assert!(
        factory
            .encoder(
                &EncoderSpec::from_json(&wrong.to_string()).unwrap(),
                &original_runtime()
            )
            .is_err()
    );
    assert!(factory.judge(&spec, &original_runtime()).is_err());
}

#[test]
fn invalid_profile_identity_and_unaccredited_runtime_fail_before_loading_weights() {
    let temp = tempfile::tempdir().unwrap();
    let factory = cold_factory(temp.path());
    let spec = ModelCatalog::built_in().unwrap().static_spec();
    for change in [
        json!({"revision":"a".repeat(64)}),
        json!({"model_id":"unknown/table"}),
        json!({"backend":"provided"}),
    ] {
        let mut value = serde_json::to_value(&spec).unwrap();
        for (key, value_change) in change.as_object().unwrap() {
            value[key] = value_change.clone();
        }
        assert!(
            factory
                .encoder(
                    &EncoderSpec::from_json(&value.to_string()).unwrap(),
                    &original_runtime()
                )
                .is_err()
        );
    }
    let mut capture: Value =
        serde_json::from_str(include_str!("fixtures/profile-identity/macos.json")).unwrap();
    capture["legacy_runtime"]["backends"]["static"][0][1] = json!("unaccredited-version");
    let changed = LegacyRuntimeIdentity::from_json(&capture["legacy_runtime"].to_string()).unwrap();
    assert!(factory.encoder(&spec, &changed).is_err());
}

#[test]
fn concurrent_profile_requests_share_one_owner_and_the_fifth_evicts_only_factory_references() {
    let temp = tempfile::tempdir().unwrap();
    let factory = cold_factory(temp.path());
    let spec = ModelCatalog::built_in().unwrap().static_spec();
    let legacy = original_runtime();
    let owners = std::thread::scope(|scope| {
        let jobs: Vec<_> = (0..8)
            .map(|_| scope.spawn(|| factory.encoder(&spec, &legacy).unwrap()))
            .collect();
        jobs.into_iter()
            .map(|job| job.join().unwrap())
            .collect::<Vec<_>>()
    });
    assert!(owners.iter().all(|owner| Arc::ptr_eq(owner, &owners[0])));
    let first = Arc::downgrade(&owners[0]);
    let live_caller = owners[0].clone();
    drop(owners);
    for budget in 1..=4 {
        let mut changed = spec.clone();
        changed.batch_size = budget;
        factory.encoder(&changed, &legacy).unwrap();
    }
    assert!(
        first.upgrade().is_some(),
        "eviction must not destroy a live caller"
    );
    drop(live_caller);
    assert!(
        first.upgrade().is_none(),
        "factory must retain at most four owners"
    );
}

#[test]
fn a_corrupt_bundled_table_never_becomes_a_prepared_encoder() {
    let temp = tempfile::tempdir().unwrap();
    let bundled = temp.path().join("table.npz");
    std::fs::write(&bundled, b"wrong").unwrap();
    let resources = PreparedModelResources::new(&temp.path().join("owned"), &bundled).unwrap();
    let factory = ModelFactory::new(
        ModelCatalog::built_in().unwrap(),
        ArtifactCache::new(&temp.path().join("cache")).unwrap(),
        resources,
        AcquisitionPolicy::Offline,
    );
    let encoder = factory
        .encoder(
            &ModelCatalog::built_in().unwrap().static_spec(),
            &original_runtime(),
        )
        .unwrap();
    assert!(encoder.dim().is_err());
    assert!(!encoder.is_prepared().unwrap());
}

#[test]
fn role_accessors_and_empty_or_english_calls_do_not_acquire_sources_or_load_sdks() {
    use ken_models::NativeOnnxRuntime;
    let temp = tempfile::tempdir().unwrap();
    let mut resources =
        PreparedModelResources::new(&temp.path().join("owned"), &temp.path().join("absent.npz"))
            .unwrap();
    let registration = json!({"format":"ken-native-onnx/1","libraries":[{
        "os":std::env::consts::OS,"arch":std::env::consts::ARCH,"version":"1.25.1","api":25,
        "bytes":1,"sha256":"0".repeat(64)
    }]});
    resources.onnx = Some(
        NativeOnnxRuntime::from_json(
            &registration.to_string(),
            &temp.path().join("absent-runtime"),
        )
        .unwrap(),
    );
    let factory = ModelFactory::new(
        ModelCatalog::built_in().unwrap(),
        ArtifactCache::new(&temp.path().join("cache")).unwrap(),
        resources,
        AcquisitionPolicy::Offline,
    );
    let context = factory.context().unwrap();
    assert_eq!(context.dim(), 768);
    assert!(context.embed_passages(&[]).unwrap().is_empty());
    assert!(!context.is_prepared().unwrap());
    let reranker = factory.reranker().unwrap();
    assert!(reranker.score("hello", &[]).unwrap().scores.is_empty());
    assert!(!reranker.is_prepared().unwrap());
    let expansion = factory.expansion().unwrap();
    assert_eq!(expansion.expand("hello").unwrap(), "hello");
    assert!(!expansion.is_loaded());
    assert!(!temp.path().join("owned").exists());
}

#[test]
fn judge_selection_is_cold_and_its_original_load_error_happens_on_score() {
    use ken_models::NativeTransformerRuntime;
    let temp = tempfile::tempdir().unwrap();
    let mut resources =
        PreparedModelResources::new(&temp.path().join("owned"), &temp.path().join("absent.npz"))
            .unwrap();
    let runtime = json!({"format":"ken-native-transformer/1","backend":"torch","runtimes":[{
        "os":std::env::consts::OS,"arch":std::env::consts::ARCH,"core_version":"2.9.0",
        "module":{"bytes":1,"sha256":"0".repeat(64)},"libraries":{"lib/core":{"bytes":1,"sha256":"0".repeat(64)}}
    }]});
    resources.torch = Some(
        NativeTransformerRuntime::from_json(
            &runtime.to_string(),
            &temp.path().join("absent-module"),
            &temp.path().join("absent-core"),
        )
        .unwrap(),
    );
    let catalog: Value =
        serde_json::from_str(include_str!("../resources/transformer-catalog.json")).unwrap();
    let judge = catalog["models"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["role"] == "judge")
        .unwrap();
    let spec = EncoderSpec::from_json(&json!({"model_id":judge["name"],"revision":judge["assets"]["revision"],"backend":"sentence-transformers"}).to_string()).unwrap();
    let capture: Value =
        serde_json::from_str(include_str!("fixtures/profile-identity/macos-torch.json")).unwrap();
    let legacy = LegacyRuntimeIdentity::from_json(&capture["legacy_runtime"].to_string()).unwrap();
    let factory = ModelFactory::new(
        ModelCatalog::built_in().unwrap(),
        ArtifactCache::new(&temp.path().join("cache")).unwrap(),
        resources,
        AcquisitionPolicy::Offline,
    );
    let owner = factory.judge(&spec, &legacy).unwrap();
    assert!(owner.preparation().unwrap().is_none());
    assert!(!temp.path().join("owned").exists());
    assert!(owner.score("hello", &[], "implementation").is_err());
    assert!(owner.preparation().unwrap().is_none());
}

#[test]
fn cold_judge_rejects_crossed_runtime_declarations() {
    use ken_models::NativeTransformerRuntime;
    let pairs = if cfg!(target_os = "macos") {
        vec![("mlx", "torch"), ("sentence-transformers", "mlx")]
    } else {
        vec![("mlx", "torch")]
    };
    for (profile_backend, runtime_backend) in pairs {
        let temp = tempfile::tempdir().unwrap();
        let mut resources = PreparedModelResources::new(
            &temp.path().join("owned"),
            &temp.path().join("absent.npz"),
        )
        .unwrap();
        let declaration = json!({"format":"ken-native-transformer/1","backend":runtime_backend,"runtimes":[{
            "os":std::env::consts::OS,"arch":std::env::consts::ARCH,
            "core_version":if runtime_backend=="mlx" {"0.32.3"} else {"2.9.0"},
            "module":{"bytes":1,"sha256":"0".repeat(64)},
            "libraries":{"lib/core":{"bytes":1,"sha256":"0".repeat(64)}}
        }]});
        let runtime = NativeTransformerRuntime::from_json(
            &declaration.to_string(),
            &temp.path().join("absent-module"),
            &temp.path().join("absent-core"),
        )
        .unwrap();
        if profile_backend == "mlx" {
            resources.mlx = Some(runtime.clone());
        } else {
            resources.torch = Some(runtime.clone());
        }
        let catalog: Value =
            serde_json::from_str(include_str!("../resources/transformer-catalog.json")).unwrap();
        let model = catalog["models"]
            .as_array()
            .unwrap()
            .iter()
            .find(|m| m["role"] == "judge")
            .unwrap();
        let spec = EncoderSpec::from_json(
            &json!({"model_id":model["name"],
            "revision":model["assets"]["revision"],"backend":profile_backend})
            .to_string(),
        )
        .unwrap();
        let original = if profile_backend == "mlx" {
            include_str!("fixtures/profile-identity/macos-mlx.json")
        } else {
            include_str!("fixtures/profile-identity/macos-torch.json")
        };
        let capture: Value = serde_json::from_str(original).unwrap();
        let legacy =
            LegacyRuntimeIdentity::from_json(&capture["legacy_runtime"].to_string()).unwrap();
        let factory = ModelFactory::new(
            ModelCatalog::built_in().unwrap(),
            ArtifactCache::new(&temp.path().join("cache")).unwrap(),
            resources,
            AcquisitionPolicy::Offline,
        );
        let error = factory
            .judge(&spec, &legacy)
            .err()
            .expect("crossed runtime must fail cold");
        assert!(error.to_string().contains("runtime backend"), "{error}");
        assert!(runtime.loaded_identity().unwrap().is_none());
        assert!(!temp.path().join("owned").exists());
    }
}
