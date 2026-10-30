//! Explicit real-core probe, not full-model or universal numeric qualification.
//!
//! The parent runs this ignored test in the normal ken-models test process with
//! an existing, unchanged Torch2.9.0 module/SDK declaration and a distinct normal
//! namespace OpenMP library. It never builds a backend, patches an SDK, launches
//! Python or captures/replays a model matrix.
#![cfg(all(target_os = "linux", target_arch = "x86_64", target_env = "gnu"))]

use ken_models::{
    ModelFileSource, NativeTransformerRuntime, TransformerBatch, TransformerDevice,
    TransformerDtype, TransformerModel, TransformerNativeArtifact, TransformerOutput,
    TransformerSession,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File},
    io::Read,
    path::{Path, PathBuf},
    sync::Arc,
};

fn artifact(path: &Path) -> TransformerNativeArtifact {
    let mut file = File::open(path).unwrap();
    let before = file.metadata().unwrap();
    let mut digest = Sha256::new();
    let mut buffer = [0; 64 * 1024];
    loop {
        let count = file.read(&mut buffer).unwrap();
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    let after = file.metadata().unwrap();
    assert_eq!(before.len(), after.len(), "artifact changed while hashing");
    assert_eq!(before.modified().unwrap(), after.modified().unwrap());
    TransformerNativeArtifact {
        bytes: after.len(),
        sha256: format!("{:x}", digest.finalize()),
    }
}

fn explicit_path(name: &str) -> PathBuf {
    let path = PathBuf::from(std::env::var_os(name).unwrap_or_else(|| {
        panic!("ignored real-core probe requires explicit {name}; no ambient SDK fallback")
    }));
    assert!(path.is_absolute(), "{name} must be absolute");
    path
}

fn save(directory: &Path, name: &str, value: &impl serde::Serialize) {
    fs::write(
        directory.join(name),
        serde_json::to_vec_pretty(value).unwrap(),
    )
    .unwrap();
}

fn executable_images(directory: &Path, phase: &str) -> BTreeSet<PathBuf> {
    let raw = fs::read_to_string("/proc/self/maps").unwrap();
    fs::write(directory.join(format!("{phase}.maps")), &raw).unwrap();
    raw.lines()
        .filter_map(|line| {
            let fields = line.split_whitespace().collect::<Vec<_>>();
            if fields.len() < 6 || !fields[1].contains('x') || !fields[5].starts_with('/') {
                return None;
            }
            let path = fields[5..].join(" ");
            assert!(
                !path.ends_with(" (deleted)"),
                "live namespace proof needs readable mapped backing bytes: {path}"
            );
            Some(PathBuf::from(path).canonicalize().unwrap())
        })
        .collect()
}

fn prepared_model(root: &Path) -> (TransformerModel, Arc<ken_models::VerifiedModelFiles>) {
    let source = root.join("model-source").join("6".repeat(40));
    fs::create_dir_all(&source).unwrap();
    let config: Value = serde_json::from_str(include_str!(
        "../../../native/ken-torch-backend/tests/fixtures/qwen/config.json"
    ))
    .unwrap();
    let configs = json!({
        "config.json": config,
        "modules.json": [
            {"idx":0,"type":"sentence_transformers.models.Transformer","path":""},
            {"idx":1,"type":"sentence_transformers.models.Pooling","path":"1_Pooling"},
            {"idx":2,"type":"sentence_transformers.models.Normalize","path":"2_Normalize"}
        ],
        "1_Pooling/config.json": {
            "word_embedding_dimension":4,
            "pooling_mode_lasttoken":true
        }
    });
    let mut artifacts = BTreeMap::new();
    for (name, value) in configs.as_object().unwrap() {
        let path = source.join(name);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, serde_json::to_vec(value).unwrap()).unwrap();
        artifacts.insert(name.clone(), artifact(&path));
    }
    // This public typed probe supplies the existing fixture's token IDs directly;
    // a registered placeholder is not a tokenizer-inference qualification claim.
    for (name, bytes) in [
        ("tokenizer.json", b"{}".as_slice()),
        (
            "model.safetensors",
            include_bytes!(
                "../../../native/ken-torch-backend/tests/fixtures/qwen/model.safetensors"
            )
            .as_slice(),
        ),
    ] {
        fs::write(source.join(name), bytes).unwrap();
        artifacts.insert(name.into(), artifact(&source.join(name)));
    }
    let model = TransformerModel::from_json(
        &json!({
            "name":"fixture/namespace-tiny-qwen3",
            "assets":{
                "model_id":"fixture/namespace-tiny-qwen3",
                "revision":"6".repeat(40),"license":"fixture","artifacts":artifacts
            },
            "dimension":4,"architecture":"qwen3","weight_layout":"unprefixed",
            "role":"encoder","configs":configs
        })
        .to_string(),
    )
    .unwrap();
    let files = Arc::new(
        model
            .assets()
            .verify_files(&ModelFileSource::new(&source, root).unwrap())
            .unwrap(),
    );
    fs::remove_dir_all(source).unwrap();
    (model, files)
}

fn assert_close(actual: &[f32], expected: &[f32]) {
    assert_eq!(actual.len(), expected.len());
    for (i, (actual, expected)) in actual.iter().zip(expected).enumerate() {
        assert!(actual.is_finite(), "nonfinite tiny-fixture output[{i}]");
        assert!(
            (actual - expected).abs() <= 1e-6,
            "tiny Qwen CPU F32 output[{i}] {actual} != {expected}"
        );
    }
}

#[test]
#[ignore = "explicit existing Torch2.9 SDK/package declaration, host OpenMP and fresh evidence directory required"]
fn unchanged_torch_sdk_runs_typed_qwen_with_host_openmp_preloaded_and_owned_lifetimes() {
    let declaration_path = explicit_path("KEN_TEST_TORCH_PACKAGE_DECLARATION");
    let host_openmp = explicit_path("KEN_TEST_HOST_OPENMP")
        .canonicalize()
        .unwrap();
    let evidence = explicit_path("KEN_TEST_TORCH_NAMESPACE_EVIDENCE");
    assert!(
        !evidence.exists(),
        "fresh namespace evidence directory required"
    );
    fs::create_dir_all(&evidence).unwrap();
    let declaration: Value = serde_json::from_slice(&fs::read(&declaration_path).unwrap()).unwrap();
    assert_eq!(declaration["format"], "ken-package-transformers/1");
    let registration = &declaration["torch"]["registration"];
    assert_eq!(registration["backend"], "torch");
    let row = registration["runtimes"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["os"] == "linux" && row["arch"] == "x86_64")
        .unwrap();
    assert_eq!(row["core_version"], "2.9.0");
    let libraries: BTreeMap<String, TransformerNativeArtifact> =
        serde_json::from_value(row["libraries"].clone()).unwrap();
    assert_eq!(
        libraries.len(),
        6,
        "this probe is the unchanged six-library SDK closure"
    );
    let module_member = declaration["torch"]["module_path"].as_str().unwrap();
    let module_entry = &declaration["files"][module_member];
    let module_path = Path::new(module_entry["source"].as_str().unwrap());
    let expected_module: TransformerNativeArtifact =
        serde_json::from_value(row["module"].clone()).unwrap();
    assert_eq!(artifact(module_path), expected_module);
    assert_eq!(module_entry["artifact"], row["module"]);
    let root_member = declaration["torch"]["core_root"].as_str().unwrap();
    let mut core_root = None;
    for (relative, expected) in &libraries {
        let member = format!("{root_member}/{relative}");
        let entry = &declaration["files"][&member];
        let path = Path::new(entry["source"].as_str().unwrap());
        assert!(path.is_absolute());
        assert_eq!(artifact(path), *expected, "SDK bytes changed: {relative}");
        assert_eq!(entry["artifact"], serde_json::to_value(expected).unwrap());
        let mut root = path.to_owned();
        for _ in Path::new(relative).components() {
            root.pop();
        }
        assert_eq!(root.join(relative), path);
        if let Some(previous) = &core_root {
            assert_eq!(
                &root, previous,
                "SDK declaration must use one original root"
            );
        }
        core_root = Some(root);
    }
    let core_root = core_root.unwrap();

    // Bind the normal namespace poison library to its authenticated package
    // inventory, not just a libgomp basename or an ambient loader search path.
    let release = host_openmp.parent().unwrap().parent().unwrap();
    let inventory: Value =
        serde_json::from_slice(&fs::read(release.join("FILES.json")).unwrap()).unwrap();
    let member = host_openmp.strip_prefix(release).unwrap().to_str().unwrap();
    let host_entry = &inventory["files"][member];
    let host_expected: TransformerNativeArtifact =
        serde_json::from_value(json!({"bytes":host_entry["bytes"],"sha256":host_entry["sha256"]}))
            .unwrap();
    assert_eq!(artifact(&host_openmp), host_expected);
    assert_ne!(
        libraries["lib/libgomp.so.1"].sha256, host_expected.sha256,
        "the SDK and host OpenMP hashes must remain distinct"
    );
    save(
        &evidence,
        "source-identities.json",
        &json!({
            "declaration": declaration_path,"declaration_identity":artifact(&declaration_path),
            "module":expected_module,"libraries":libraries,
            "host_openmp":{"path":host_openmp,"identity":host_expected},
            "scope":"unchanged tiny Qwen CPU Float32 namespace/lifetime proof only"
        }),
    );

    // SAFETY: the parent explicitly selected and the test authenticated this
    // normal-namespace native library. Keep its owner alive for the whole test.
    let host_library = unsafe {
        libloading::os::unix::Library::open(Some(&host_openmp), libc::RTLD_NOW | libc::RTLD_GLOBAL)
    }
    .unwrap();
    // SAFETY: OpenMP's documented no-argument int ABI, borrowed from live owner.
    let host_threads = unsafe {
        host_library.get::<unsafe extern "C" fn() -> std::ffi::c_int>(b"omp_get_max_threads\0")
    }
    .unwrap();
    assert!(unsafe { host_threads() } > 0);
    let before = executable_images(&evidence, "before-torch");
    assert!(
        before.contains(&host_openmp),
        "actual host OpenMP preload missing"
    );

    let runtime =
        NativeTransformerRuntime::from_json(&registration.to_string(), module_path, &core_root)
            .unwrap();
    assert!(runtime.loaded_identity().unwrap().is_none());
    let runtime_clone = runtime.clone();
    let work = tempfile::tempdir().unwrap();
    let (model, files) = prepared_model(work.path());
    let weak_files = Arc::downgrade(&files);
    let expected_fingerprint = files.fingerprint().to_owned();
    let mut session = TransformerSession::prepare(
        &model,
        files.clone(),
        runtime.clone(),
        TransformerDevice::Cpu,
        TransformerDtype::Float32,
    )
    .unwrap();
    assert_eq!(session.trace().core_version, "2.9.0");
    assert_eq!(session.trace().runtime.backend, "torch");
    assert_eq!(session.trace().device, TransformerDevice::Cpu);
    assert_eq!(session.trace().dtype, TransformerDtype::Float32);
    assert_eq!(session.trace().model_fingerprint, expected_fingerprint);
    assert_eq!(runtime.load().unwrap(), session.trace().runtime);

    let during = executable_images(&evidence, "session-live");
    let private_module = during
        .iter()
        .find(|path| {
            path.file_name()
                .is_some_and(|n| n == "ken_model_backend.so")
        })
        .expect("public runtime must map its authenticated private backend module");
    let private_root = private_module.parent().unwrap().to_owned();
    assert_ne!(private_root, core_root);
    assert_eq!(artifact(private_module), expected_module);
    let mut mapped = BTreeMap::new();
    for (relative, expected) in &libraries {
        let path = private_root.join(relative).canonicalize().unwrap();
        assert!(
            during.contains(&path),
            "declared SDK dependency not actually mapped: {relative}"
        );
        assert_eq!(
            artifact(&path),
            *expected,
            "mapped SDK bytes differ: {relative}"
        );
        mapped.insert(path, expected.clone());
    }
    assert!(during.contains(&host_openmp));
    assert_eq!(artifact(&host_openmp), host_expected);
    save(
        &evidence,
        "actual-private-closure.json",
        &json!({
            "module":{"path":private_module,"identity":artifact(private_module)},
            "private_dependencies":mapped,"host_openmp":{"path":host_openmp,"identity":host_expected}
        }),
    );

    drop(runtime_clone);
    drop(runtime);
    drop(files);
    assert!(
        weak_files.upgrade().is_some(),
        "session must own verified model files"
    );
    assert!(
        private_root.exists(),
        "session must pin copied SDK/library owner"
    );
    let reference: Value = serde_json::from_str(include_str!(
        "../../../native/ken-torch-backend/tests/fixtures/qwen/original.json"
    ))
    .unwrap();
    let case = reference["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|case| {
            case["name"] == "padding" && case["device"] == "cpu" && case["dtype"] == "float32"
        })
        .unwrap();
    let expected: Vec<f32> = serde_json::from_value(case["sentence_vectors"].clone()).unwrap();
    let batch = TransformerBatch {
        input_ids: serde_json::from_value(case["input_ids"].clone()).unwrap(),
        attention_mask: serde_json::from_value(case["attention_mask"].clone()).unwrap(),
    };
    let first = session.run(&batch, &TransformerOutput::Sentence).unwrap();
    assert_eq!((first.rows, first.columns), (2, 4));
    assert_close(&first.values, &expected);
    // Independent backend result allocations are decoded/copied and released
    // through their original ABI while the last session still pins the owner.
    let second = session.run(&batch, &TransformerOutput::Sentence).unwrap();
    assert_close(&second.values, &expected);
    save(
        &evidence,
        "typed-results.json",
        &json!({"first":first,"second":second}),
    );
    drop(session);
    assert!(
        weak_files.upgrade().is_none(),
        "last session must release model files"
    );
    assert!(
        !private_root.exists(),
        "last owner must remove its private SDK copy"
    );
    // Host-owned decoded results remain valid after backend/session destruction.
    assert_close(&first.values, &expected);
    assert_close(&second.values, &expected);
    assert!(
        unsafe { host_threads() } > 0,
        "normal namespace OpenMP still works"
    );
    let after = fs::read_to_string("/proc/self/maps").unwrap();
    fs::write(evidence.join("after-session-drop.maps"), after).unwrap();
    save(
        &evidence,
        "RESULT.json",
        &json!({
            "status":"PASS","core":"2.9.0","device":"cpu","dtype":"float32",
            "actual_private_libraries":6,"host_sdk_openmp_hashes_distinct":true,
            "runtime_clones_dropped_before_runs":true,"results_owned_after_session_drop":true,
            "full_registered_model_qualification":false
        }),
    );
}
