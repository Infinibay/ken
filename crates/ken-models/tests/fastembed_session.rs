use ken_models::{
    EmbeddingSession, FastEmbedDevice, FastEmbedDeviceRequest, FastEmbedModel, FastEmbedTokens,
    ModelFileSource, NativeOnnxRuntime, VerifiedModelFiles,
};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{fs, path::PathBuf, sync::Arc};

fn runtime() -> NativeOnnxRuntime {
    NativeOnnxRuntime::from_json(
        include_str!(
            "../../../docs/validation/rust-migration-2026-10-18/m2-context/runtime-libraries.json"
        ),
        &PathBuf::from(std::env::var_os("KEN_ORT_LIBRARY").expect("prepare KEN_ORT_LIBRARY")),
    )
    .unwrap()
}
fn fixture(
    graph: &str,
    pooling: &str,
) -> (tempfile::TempDir, FastEmbedModel, Arc<VerifiedModelFiles>) {
    let temp = tempfile::tempdir().unwrap();
    let source = temp.path().join("1111111111111111111111111111111111111111");
    let private = temp.path().join("private");
    fs::create_dir(&source).unwrap();
    fs::create_dir(&private).unwrap();
    let graph_bytes = fs::read(
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("tests/fixtures/fastembed")
            .join(format!("{graph}.onnx")),
    )
    .unwrap();
    let mut artifacts = serde_json::Map::new();
    for (name, bytes) in [
        ("model.onnx", graph_bytes.as_slice()),
        ("tokenizer.json", b"{}".as_slice()),
        ("config.json", b"{}"),
        ("tokenizer_config.json", b"{}"),
        ("special_tokens_map.json", b"{}"),
    ] {
        fs::write(source.join(name), bytes).unwrap();
        artifacts.insert(
            name.into(),
            json!({"bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(bytes))}),
        );
    }
    let model=FastEmbedModel::from_json(&json!({"format":"ken-fastembed-model/1","name":"test/session","assets":{"model_id":"test/session","revision":"1111111111111111111111111111111111111111","artifacts":artifacts},"graph":"model.onnx","dimension":2,"pooling":pooling,"task_id":if graph=="task"{json!(1)}else{json!(null)},"advisories":[]}).to_string()).unwrap();
    let files = Arc::new(
        model
            .assets()
            .verify_files(&ModelFileSource::new(&source, &private).unwrap())
            .unwrap(),
    );
    (temp, model, files)
}
fn tokens() -> FastEmbedTokens {
    FastEmbedTokens {
        shape: [1, 2],
        ids: vec![3, 4],
        attention_mask: vec![1, 1],
    }
}

#[test]
fn actual_cpu_inference_owns_rows_and_declared_files_through_session_drop() {
    let (temp, model, files) = fixture("hidden", "mean");
    let mut session = EmbeddingSession::prepare(
        &model,
        files.clone(),
        runtime(),
        &FastEmbedDeviceRequest::from_inputs(Some("cpu"), None),
    )
    .unwrap();
    let p = session.preparation();
    assert_eq!(p.device, FastEmbedDevice::Cpu);
    assert_eq!(p.configured_providers, vec!["CPUExecutionProvider"]);
    assert_eq!(p.attempts.len(), 1);
    assert!(p.attempts[0].error.is_none());
    assert_eq!(
        p.verified_artifacts_fingerprint.as_deref(),
        Some(files.fingerprint())
    );
    assert_eq!(session.thread_policy(), [0, 0]);
    assert!(session.cpu_arena());
    assert_eq!(session.optimization(), "ORT_ENABLE_ALL");
    let held = session.run(&tokens()).unwrap();
    assert_eq!(held.vectors, vec![vec![3.5, 3.5]]);
    assert_eq!(held.trace.output_shape, vec![1, 2, 2]);
    assert_eq!(held.trace.output_dtype, "float32");
    fs::remove_dir_all(temp.path().join(model.source_revision())).unwrap();
    drop(files);
    let mut changed = tokens();
    changed.ids = vec![10, 20];
    assert_eq!(session.run(&changed).unwrap().vectors, vec![vec![15., 15.]]);
    assert_eq!(held.vectors, vec![vec![3.5, 3.5]]);
    assert_eq!(
        fs::read_dir(temp.path().join("private")).unwrap().count(),
        1
    );
    drop(session);
    assert_eq!(
        fs::read_dir(temp.path().join("private")).unwrap().count(),
        0
    );
}

#[test]
fn graph_inputs_are_exact_with_optional_zero_types_and_scalar_task_one() {
    for graph in ["clip", "task"] {
        let (_temp, model, files) = fixture(graph, if graph == "clip" { "raw" } else { "mean" });
        let mut session = EmbeddingSession::prepare(
            &model,
            files,
            runtime(),
            &FastEmbedDeviceRequest::from_inputs(None, None),
        )
        .unwrap();
        let output = session.run(&tokens()).unwrap();
        let inputs = &output.trace.inputs;
        assert_eq!(inputs["input_ids"].values, vec![3, 4]);
        if graph == "clip" {
            assert_eq!(inputs.len(), 1);
            assert_eq!(output.vectors, vec![vec![3., 4.]]);
        } else {
            assert_eq!(inputs.len(), 4);
            assert_eq!(inputs["token_type_ids"].values, vec![0, 0]);
            assert_eq!(inputs["task_id"].values, vec![1]);
            assert!(inputs["task_id"].shape.is_empty());
        }
    }
}

#[test]
fn incompatible_graph_inputs_outputs_and_malformed_token_batches_are_errors() {
    for graph in [
        "wrong_type",
        "extra_rows",
        "nonfinite",
        "unknown_input",
        "wrong_input_type",
    ] {
        let (_temp, model, files) = fixture(
            graph,
            if graph == "extra_rows" || graph == "nonfinite" {
                "raw"
            } else {
                "mean"
            },
        );
        let session = EmbeddingSession::prepare(
            &model,
            files,
            runtime(),
            &FastEmbedDeviceRequest::from_inputs(Some("cpu"), None),
        );
        if graph == "unknown_input" || graph == "wrong_input_type" {
            assert!(session.is_err(), "{graph}");
        } else {
            assert!(session.unwrap().run(&tokens()).is_err(), "{graph}");
        }
    }
    let (_temp, model, files) = fixture("hidden", "mean");
    let mut session = EmbeddingSession::prepare(
        &model,
        files,
        runtime(),
        &FastEmbedDeviceRequest::from_inputs(None, None),
    )
    .unwrap();
    for batch in [
        FastEmbedTokens {
            shape: [usize::MAX, 2],
            ids: vec![],
            attention_mask: vec![],
        },
        FastEmbedTokens {
            shape: [1, 2],
            ids: vec![1],
            attention_mask: vec![1, 1],
        },
        FastEmbedTokens {
            shape: [1, 2],
            ids: vec![1, 2],
            attention_mask: vec![1, 2],
        },
    ] {
        assert!(session.run(&batch).is_err());
    }
}
