use ken_models::{
    FastEmbedCatalog, FastEmbedDevice, FastEmbedDeviceRequest, FastEmbedEncoder, FastEmbedInput,
    FastEmbedModel, ModelFileSource, NativeOnnxRuntime,
};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::PathBuf,
    sync::{Arc, Barrier},
};

fn runtime(path: Option<PathBuf>) -> NativeOnnxRuntime {
    NativeOnnxRuntime::from_json(
        include_str!("../resources/onnx-runtime-libraries.json"),
        &path.unwrap_or_else(|| {
            PathBuf::from(std::env::var_os("KEN_ORT_LIBRARY").expect("prepare KEN_ORT_LIBRARY"))
        }),
    )
    .unwrap()
}
struct Fixture {
    temp: tempfile::TempDir,
    model: FastEmbedModel,
    source: ModelFileSource,
    snapshot: PathBuf,
    private: PathBuf,
    graph: Vec<u8>,
}
impl Fixture {
    fn new() -> Self {
        let temp = tempfile::tempdir().unwrap();
        let snapshot = temp.path().join("1111111111111111111111111111111111111111");
        let private = temp.path().join("private");
        fs::create_dir(&snapshot).unwrap();
        fs::create_dir(&private).unwrap();
        let graph = fs::read(
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/fastembed/hidden.onnx"),
        )
        .unwrap();
        let tokenizer=json!({"version":"1.0","truncation":null,"padding":null,"added_tokens":[],"normalizer":null,"pre_tokenizer":{"type":"Whitespace"},"post_processor":null,"decoder":null,"model":{"type":"WordLevel","vocab":{"[UNK]":0,"[PAD]":1,"a":2,"b":3},"unk_token":"[UNK]"}}).to_string();
        let mut artifacts = serde_json::Map::new();
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
                json!({"bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(bytes))}),
            );
        }
        let model=FastEmbedModel::from_json(&json!({"format":"ken-fastembed-model/1","name":"test/encoder","assets":{"model_id":"test/encoder","revision":"1111111111111111111111111111111111111111","artifacts":artifacts},"graph":"model.onnx","dimension":2,"pooling":"mean","task_id":null,"advisories":[]}).to_string()).unwrap();
        let source = ModelFileSource::new(&snapshot, &private).unwrap();
        Self {
            temp,
            model,
            source,
            snapshot,
            private,
            graph,
        }
    }
    fn encoder(&self, runtime: NativeOnnxRuntime) -> FastEmbedEncoder {
        FastEmbedEncoder::new(
            self.model.clone(),
            self.source.clone(),
            runtime,
            FastEmbedDeviceRequest::from_inputs(Some("cpu"), None),
        )
        .unwrap()
    }
}

#[test]
fn construction_and_empty_batches_need_neither_models_nor_runtime() {
    let fixture = Fixture::new();
    fs::remove_dir_all(&fixture.snapshot).unwrap();
    fs::remove_dir(&fixture.private).unwrap();
    let encoder = fixture.encoder(runtime(Some(fixture.temp.path().join("missing-runtime"))));
    assert_eq!(encoder.dim(), 2);
    assert!(!encoder.is_prepared().unwrap());
    assert_eq!(encoder.device().unwrap(), FastEmbedDevice::Unknown);
    assert!(encoder.embed_queries(&[]).unwrap().is_empty());
    assert!(encoder.embed_passages(&[]).unwrap().is_empty());
    assert!(
        encoder
            .tokenize(&[], FastEmbedInput::Query)
            .unwrap()
            .is_empty()
    );
    let details = encoder.embed_details(&[], FastEmbedInput::Passage).unwrap();
    assert!(details.vectors.is_empty());
    assert!(details.batches.is_empty());
    assert!(details.preparation.runtime.is_none());
    assert!(details.preparation.verified_artifacts_fingerprint.is_none());
    assert!(details.preparation.attempts.is_empty());
    assert!(!fixture.private.exists());
    let catalog =
        FastEmbedCatalog::from_json(include_str!("../resources/fastembed-catalog.json")).unwrap();
    for name in ["Qdrant/clip-ViT-B-32-text", "jinaai/jina-embeddings-v3"] {
        let model = catalog.model(name).unwrap().clone();
        let source = ModelFileSource::new(
            &fixture.temp.path().join(model.source_revision()),
            &fixture.private,
        )
        .unwrap();
        let expected = model.dim();
        let encoder = FastEmbedEncoder::new(
            model,
            source,
            runtime(Some(fixture.temp.path().join("absent"))),
            FastEmbedDeviceRequest::from_inputs(None, None),
        )
        .unwrap();
        assert_eq!(encoder.dim(), expected);
        assert!(expected == 512 || expected == 1024);
        assert!(!encoder.is_prepared().unwrap());
    }
}

#[test]
fn lexical_diagnostic_loads_only_configs_and_cpu_preparation_can_retry_real_repairs() {
    let fixture = Fixture::new();
    fs::remove_file(fixture.snapshot.join("model.onnx")).unwrap();
    let library = fixture.temp.path().join("runtime-alias");
    let encoder = fixture.encoder(runtime(Some(library.clone())));
    assert_eq!(
        encoder.tokenize(&["a b"], FastEmbedInput::Query).unwrap()[0].ids,
        vec![2, 3]
    );
    assert!(!encoder.is_prepared().unwrap());
    assert_eq!(encoder.device().unwrap(), FastEmbedDevice::Unknown);
    assert_eq!(fs::read_dir(&fixture.private).unwrap().count(), 0);
    assert!(encoder.prepare().is_err());
    assert_eq!(fs::read_dir(&fixture.private).unwrap().count(), 0);
    fs::write(fixture.snapshot.join("model.onnx"), &fixture.graph).unwrap();
    assert!(encoder.prepare().is_err());
    assert!(!encoder.is_prepared().unwrap());
    assert_eq!(encoder.device().unwrap(), FastEmbedDevice::Unknown);
    assert_eq!(fs::read_dir(&fixture.private).unwrap().count(), 0);
    fs::copy(
        PathBuf::from(std::env::var_os("KEN_ORT_LIBRARY").unwrap()),
        &library,
    )
    .unwrap();
    assert_eq!(encoder.embed_queries(&["a"]).unwrap(), vec![vec![2., 2.]]);
    assert!(encoder.is_prepared().unwrap());
    assert_eq!(encoder.device().unwrap(), FastEmbedDevice::Cpu);
    assert_eq!(fs::read_dir(&fixture.private).unwrap().count(), 1);
    fs::remove_dir_all(&fixture.snapshot).unwrap();
    fs::remove_file(library).unwrap();
    assert_eq!(encoder.embed_passages(&["b"]).unwrap(), vec![vec![3., 3.]]);
    assert_eq!(encoder.preparation().unwrap().device, FastEmbedDevice::Cpu);
    drop(encoder);
    assert_eq!(fs::read_dir(&fixture.private).unwrap().count(), 0);
}

#[test]
fn concurrent_first_use_and_owned_results_keep_whole_requests_separate() {
    let fixture = Fixture::new();
    let encoder = Arc::new(fixture.encoder(runtime(None)));
    let barrier = Arc::new(Barrier::new(6));
    std::thread::scope(|scope| {
        for i in 0..6 {
            let encoder = encoder.clone();
            let barrier = barrier.clone();
            scope.spawn(move || {
                barrier.wait();
                for _ in 0..5 {
                    let rows = if i % 2 == 0 {
                        encoder.embed_queries(&["a"])
                    } else {
                        encoder.embed_passages(&["b"])
                    }
                    .unwrap();
                    assert_eq!(rows, vec![vec![if i % 2 == 0 { 2. } else { 3. }; 2]]);
                }
            });
        }
    });
    assert_eq!(fs::read_dir(&fixture.private).unwrap().count(), 1);
    let held = encoder
        .embed_details(&["a"], FastEmbedInput::Query)
        .unwrap();
    let mut changed = encoder.embed_passages(&["b"]).unwrap();
    changed[0][0] = 99.;
    assert_eq!(held.vectors, vec![vec![2., 2.]]);
    assert_eq!(held.batches[0].inputs["input_ids"].values, vec![2]);
    fs::remove_dir_all(&fixture.snapshot).unwrap();
    assert_eq!(encoder.embed_queries(&["a"]).unwrap(), held.vectors);
    drop(encoder);
    assert_eq!(fs::read_dir(&fixture.private).unwrap().count(), 0);
}

#[test]
fn batch257_is_chunked_before_padding_and_details_match_vectors_only() {
    let fixture = Fixture::new();
    let encoder = fixture.encoder(runtime(None));
    let mut texts = vec!["a"; 256];
    texts.push("a b a b a b");
    let details = encoder
        .embed_details(&texts, FastEmbedInput::Passage)
        .unwrap();
    assert_eq!(details.vectors.len(), 257);
    assert_eq!(details.batches.len(), 2);
    assert_eq!(details.batches[0].inputs["input_ids"].shape, vec![256, 1]);
    assert_eq!(details.batches[1].inputs["input_ids"].shape, vec![1, 6]);
    assert!(
        details.vectors[..256]
            .iter()
            .all(|row| row == &vec![2., 2.])
    );
    assert_eq!(details.vectors[256], vec![2.5, 2.5]);
    assert_eq!(encoder.embed_passages(&texts).unwrap(), details.vectors);
}

#[test]
fn failure_in_second_native_batch_never_returns_a_partial_request() {
    let mut fixture = Fixture::new();
    let graph = fs::read(
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/fastembed/late_error.onnx"),
    )
    .unwrap();
    let mut assets = serde_json::to_value(fixture.model.assets()).unwrap();
    assets["artifacts"]["model.onnx"] =
        json!({"bytes":graph.len(),"sha256":format!("{:x}",Sha256::digest(&graph))});
    fixture.model=FastEmbedModel::from_json(&json!({"format":"ken-fastembed-model/1","name":"test/encoder","assets":assets,"graph":"model.onnx","dimension":2,"pooling":"mean","task_id":null,"advisories":[]}).to_string()).unwrap();
    fs::write(fixture.snapshot.join("model.onnx"), graph).unwrap();
    let encoder = fixture.encoder(runtime(None));
    assert_eq!(encoder.embed_queries(&["a"]).unwrap(), vec![vec![-1., -1.]]);
    let mut texts = vec!["a"; 256];
    texts.push("b");
    assert!(
        encoder
            .embed_details(&texts, FastEmbedInput::Passage)
            .is_err()
    );
    assert!(encoder.embed_passages(&texts).is_err());
    assert_eq!(encoder.embed_queries(&["a"]).unwrap(), vec![vec![-1., -1.]]);
}
