//! Optional-module declarations must stay independent of filesystem availability.
use ken_models::NativeTransformerRuntime;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::path::Path;
static FIXTURE_USE: std::sync::Mutex<()> = std::sync::Mutex::new(());

fn fixture() -> std::path::PathBuf {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap();
    let target = root.join(".ken/rust-migration/m2-optional/api-fixture-target");
    let status = std::process::Command::new(env!("CARGO"))
        .args(["build", "--offline", "--manifest-path"])
        .arg(root.join("native/ken-model-test-backend/Cargo.toml"))
        .env("CARGO_TARGET_DIR", &target)
        .status()
        .unwrap();
    assert!(status.success());
    target.join("debug").join(format!(
        "{}ken_model_test_backend{}",
        std::env::consts::DLL_PREFIX,
        std::env::consts::DLL_SUFFIX
    ))
}

fn hash(bytes: &[u8]) -> Value {
    json!({"bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(bytes))})
}

fn registration() -> Value {
    json!({"format":"ken-native-transformer/1","backend":"torch","runtimes":[{
        "os":std::env::consts::OS,"arch":std::env::consts::ARCH,"core_version":"2.9.0",
        "module":{"bytes":3,"sha256":"1".repeat(64)},
        "libraries":{"libtorch.dat":{"bytes":3,"sha256":"2".repeat(64)}}
    }]})
}

#[test]
fn verified_module_aliases_and_concurrent_first_use_share_only_matching_code() {
    let _serial = FIXTURE_USE.lock().unwrap();
    let temp = tempfile::tempdir().unwrap();
    let module = temp.path().join("fixture.dylib");
    let bytes = std::fs::read(fixture()).unwrap();
    std::fs::write(&module, &bytes).unwrap();
    std::fs::write(temp.path().join("core.dat"), b"abc").unwrap();
    let mut declaration = registration();
    declaration["backend"] = json!("contract-fixture");
    declaration["runtimes"][0]["core_version"] = json!("1");
    declaration["runtimes"][0]["module"] = hash(&bytes);
    declaration["runtimes"][0]["libraries"] = json!({"core.dat":hash(b"abc")});
    let make = |value: &Value, path: &Path| {
        NativeTransformerRuntime::from_json(&value.to_string(), path, temp.path()).unwrap()
    };
    let runtime = make(&declaration, &module);
    let results = std::thread::scope(|scope| {
        let tasks: Vec<_> = (0..8)
            .map(|_| scope.spawn(|| runtime.load().unwrap()))
            .collect();
        tasks
            .into_iter()
            .map(|task| task.join().unwrap())
            .collect::<Vec<_>>()
    });
    assert!(results.iter().all(|v| v == &results[0]));
    assert_eq!(results[0].declared_core_version, "1");
    assert_eq!(runtime.loaded_identity().unwrap(), Some(results[0].clone()));
    assert_eq!(make(&declaration, &module).load().unwrap(), results[0]);
    let missing = temp.path().join("missing");
    let repaired = make(&declaration, &missing);
    assert!(repaired.load().is_err());
    std::fs::write(&missing, &bytes).unwrap();
    assert_eq!(
        repaired.load().unwrap(),
        results[0],
        "failed initialization is repairable"
    );
    drop(repaired);
    std::fs::write(temp.path().join("core.dat"), b"def").unwrap();
    assert!(make(&declaration, &module).load().is_err());
    let mut conflicting = declaration.clone();
    conflicting["runtimes"][0]["libraries"]["core.dat"] = hash(b"def");
    assert!(make(&conflicting, &module).load().is_err());
    std::fs::write(temp.path().join("core.dat"), b"abc").unwrap();
    let mut wrong_backend = declaration.clone();
    wrong_backend["backend"] = json!("torch");
    wrong_backend["runtimes"][0]["core_version"] = json!("2.9.0");
    assert!(make(&wrong_backend, &module).load().is_err());
    std::fs::write(&module, b"changed").unwrap();
    assert!(make(&declaration, &module).load().is_err());
    assert_eq!(
        runtime.load().unwrap(),
        results[0],
        "live private mapping survives source changes"
    );
    let reserved = format!("ken_model_backend{}", std::env::consts::DLL_SUFFIX);
    for name in [
        "../escape",
        "/absolute",
        "nested/../escape",
        reserved.as_str(),
    ] {
        let mut bad = declaration.clone();
        bad["runtimes"][0]["libraries"] = json!({name:hash(b"abc")});
        assert!(
            NativeTransformerRuntime::from_json(&bad.to_string(), &module, temp.path()).is_err(),
            "{name}"
        );
    }
}

#[test]
fn cold_declarations_do_not_load_optional_cores() {
    let runtime = NativeTransformerRuntime::from_json(
        &registration().to_string(),
        Path::new("/missing/module"),
        Path::new("/missing/cores"),
    )
    .unwrap();
    assert!(runtime.loaded_identity().unwrap().is_none());
    assert!(runtime.load().is_err());
    assert!(runtime.loaded_identity().unwrap().is_none());
}

#[test]
fn invalid_platform_module_and_core_declarations_fail_before_loading() {
    for (pointer, value) in [
        ("/format", json!("unknown")),
        ("/backend", json!("unknown")),
        ("/runtimes/0/core_version", json!("2.8.0")),
        ("/runtimes/0/module/bytes", json!(0)),
        ("/runtimes/0/module/sha256", json!("not-a-hash")),
        ("/runtimes/0/arch", json!("unknown")),
    ] {
        let mut value0 = registration();
        *value0.pointer_mut(pointer).unwrap() = value;
        assert!(
            NativeTransformerRuntime::from_json(
                &value0.to_string(),
                Path::new("/missing/module"),
                Path::new("/missing/core")
            )
            .is_err(),
            "{pointer}"
        );
    }
    assert!(
        NativeTransformerRuntime::from_json(
            &registration().to_string(),
            Path::new("relative"),
            Path::new("/missing/core")
        )
        .is_err()
    );
    let mut duplicate = registration();
    let row = duplicate["runtimes"][0].clone();
    duplicate["runtimes"].as_array_mut().unwrap().push(row);
    assert!(
        NativeTransformerRuntime::from_json(
            &duplicate.to_string(),
            Path::new("/missing/module"),
            Path::new("/missing/core")
        )
        .is_err()
    );
}

#[test]
fn duplicate_library_names_are_rejected_before_filesystem_access() {
    let value = registration();
    let duplicate = value.to_string().replace(
        "\"libraries\":{",
        &format!(
            "\"libraries\":{{\"libtorch.dat\":{},",
            value["runtimes"][0]["libraries"]["libtorch.dat"]
        ),
    );
    assert!(
        NativeTransformerRuntime::from_json(
            &duplicate,
            Path::new("/missing/module"),
            Path::new("/missing/core")
        )
        .is_err()
    );
}

#[test]
fn typed_session_owns_private_files_and_checks_actual_preparation_and_results() {
    let _serial = FIXTURE_USE.lock().unwrap();
    use ken_models::{
        ModelFileSource, TransformerBatch, TransformerDevice, TransformerDtype, TransformerModel,
        TransformerOutput, TransformerSession,
    };
    use std::sync::Arc;
    let temp = tempfile::tempdir().unwrap();
    let revision = "a".repeat(40);
    let source = temp.path().join(&revision);
    std::fs::create_dir(&source).unwrap();
    let log = temp.path().join("typed-lifecycle.jsonl");
    let configs = json!({
        "config.json":{"model_type":"qwen3","hidden_size":2,"vocab_size":32,"max_position_embeddings":8,"contract_fixture_log":log},
        "modules.json":[{"idx":0,"type":"sentence_transformers.models.Transformer","path":""},{"idx":1,"type":"sentence_transformers.models.Pooling","path":"1_Pooling"}],
        "1_Pooling/config.json":{"word_embedding_dimension":2,"pooling_mode_mean_tokens":true}
    });
    let mut artifacts = serde_json::Map::new();
    for (name, value) in configs.as_object().unwrap() {
        let path = source.join(name);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        let bytes = serde_json::to_vec(value).unwrap();
        std::fs::write(path, &bytes).unwrap();
        artifacts.insert(name.clone(), hash(&bytes));
    }
    for (name, bytes) in [
        ("tokenizer.json", b"{}".as_slice()),
        ("model.safetensors", b"3".as_slice()),
    ] {
        std::fs::write(source.join(name), bytes).unwrap();
        artifacts.insert(name.into(), hash(bytes));
    }
    let model=TransformerModel::from_json(&json!({"name":"fixture/typed","assets":{"model_id":"fixture/typed","revision":revision,"license":"fixture","artifacts":artifacts},
        "dimension":2,"architecture":"qwen3","weight_layout":"unprefixed","role":"encoder","configs":configs}).to_string()).unwrap();
    let files = Arc::new(
        model
            .assets()
            .verify_files(&ModelFileSource::new(&source, temp.path()).unwrap())
            .unwrap(),
    );
    let weak = Arc::downgrade(&files);
    let binary = fixture();
    let bytes = std::fs::read(&binary).unwrap();
    std::fs::write(temp.path().join("typed-core.dat"), b"abc").unwrap();
    let mut value = registration();
    value["backend"] = json!("contract-fixture");
    value["runtimes"][0]["core_version"] = json!("1");
    value["runtimes"][0]["module"] = hash(&bytes);
    value["runtimes"][0]["libraries"] = json!({"typed-core.dat":hash(b"abc")});
    let runtime =
        NativeTransformerRuntime::from_json(&value.to_string(), &binary, temp.path()).unwrap();
    let mut session = TransformerSession::prepare(
        &model,
        Arc::clone(&files),
        runtime.clone(),
        TransformerDevice::Cpu,
        TransformerDtype::Float32,
    )
    .unwrap();
    assert!(
        TransformerSession::prepare(
            &model,
            Arc::clone(&files),
            runtime.clone(),
            TransformerDevice::Mps,
            TransformerDtype::Float32
        )
        .is_err(),
        "fixture actually executes CPU, never echo requested MPS"
    );
    assert!(
        TransformerSession::prepare(
            &model,
            Arc::clone(&files),
            runtime.clone(),
            TransformerDevice::Cpu,
            TransformerDtype::Float16
        )
        .is_err(),
        "fixture arithmetic is Float32"
    );
    std::fs::remove_dir_all(&source).unwrap();
    drop(files);
    drop(runtime);
    assert!(weak.upgrade().is_some());
    let batch = TransformerBatch {
        input_ids: vec![vec![2, 4, 0]],
        attention_mask: vec![vec![1, 1, 0]],
    };
    let result = session.run(&batch, &TransformerOutput::Sentence).unwrap();
    assert_eq!((result.rows, result.columns), (1, 2));
    assert_eq!(result.values, vec![18.0, 19.0]);
    assert_eq!(result.trace.runtime.backend, "contract-fixture");
    assert_eq!(result.trace.device, TransformerDevice::Cpu);
    assert_eq!(result.trace.dtype, TransformerDtype::Float32);
    let bad = TransformerBatch {
        input_ids: vec![vec![32]],
        attention_mask: vec![vec![1]],
    };
    assert!(session.run(&bad, &TransformerOutput::Sentence).is_err());
    assert!(
        session
            .run(
                &batch,
                &TransformerOutput::YesMinusNo {
                    true_id: 1,
                    false_id: 2
                }
            )
            .is_err(),
        "encoder cannot become a judge"
    );
    drop(session);
    assert!(weak.upgrade().is_none());
    let events = std::fs::read_to_string(log).unwrap();
    assert_eq!(
        events
            .lines()
            .filter(|v| v.contains("model_opened"))
            .count(),
        3
    );
    assert_eq!(
        events
            .lines()
            .filter(|v| v.contains("model_closed"))
            .count(),
        3
    );
    assert!(events.lines().last().unwrap().contains("model_closed"));
}
