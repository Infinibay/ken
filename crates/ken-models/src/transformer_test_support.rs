//! Actual tiny model and pinned runtime, shared by contract tests only.
use crate::{ModelFileSource, NativeTransformerRuntime, TransformerModel};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
};
fn fingerprint(bytes: &[u8]) -> Value {
    json!({"bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(bytes))})
}
pub(crate) fn fixture_with_configs(
    overrides: &[(&str, Value)],
) -> (
    tempfile::TempDir,
    TransformerModel,
    ModelFileSource,
    NativeTransformerRuntime,
) {
    fixture_with_weights(overrides, None)
}
pub(crate) fn fixture_with_weights(
    overrides: &[(&str, Value)],
    weights: Option<&[u8]>,
) -> (
    tempfile::TempDir,
    TransformerModel,
    ModelFileSource,
    NativeTransformerRuntime,
) {
    let repo = Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap();
    let core = PathBuf::from(
        std::env::var_os("KEN_TORCH_CORE").expect("prepare actual pinned Torch core"),
    );
    let module = PathBuf::from(
        std::env::var_os("KEN_TORCH_MODULE").expect("prepare actual tested Torch module"),
    );
    let declaration = PathBuf::from(
        std::env::var_os("KEN_TORCH_PREPARATION").expect("prepare actual core library hashes"),
    );
    let libraries: Value = serde_json::from_slice(&std::fs::read(declaration).unwrap()).unwrap();
    let mut closure = BTreeMap::new();
    for row in libraries["libraries"].as_array().unwrap() {
        closure.insert(
            format!("lib/{}", row["name"].as_str().unwrap()),
            json!({"bytes":row["bytes"],"sha256":row["sha256"]}),
        );
    }
    let runtime=NativeTransformerRuntime::from_json(&json!({"format":"ken-native-transformer/1","backend":"torch","runtimes":[{"os":std::env::consts::OS,"arch":std::env::consts::ARCH,"core_version":"2.9.0","module":fingerprint(&std::fs::read(&module).unwrap()),"libraries":closure}]}).to_string(),&module,&core).unwrap();
    let temp = tempfile::tempdir().unwrap();
    let revision = "dddddddddddddddddddddddddddddddddddddddd";
    let snapshot = temp.path().join(revision);
    std::fs::create_dir(&snapshot).unwrap();
    let config: Value = serde_json::from_slice(
        &std::fs::read(repo.join("native/ken-torch-backend/tests/fixtures/qwen/config.json"))
            .unwrap(),
    )
    .unwrap();
    let mut configs = BTreeMap::from([
        ("config.json", config),
        (
            "tokenizer_config.json",
            json!({"pad_token":"[PAD]","model_max_length":16}),
        ),
        (
            "sentence_bert_config.json",
            json!({"max_seq_length":16,"do_lower_case":false}),
        ),
        (
            "modules.json",
            json!([{"idx":0,"name":"0","path":"","type":"sentence_transformers.models.Transformer"},{"idx":1,"name":"1","path":"1_Pooling","type":"sentence_transformers.models.Pooling"}]),
        ),
        (
            "1_Pooling/config.json",
            json!({"word_embedding_dimension":4,"pooling_mode_lasttoken":true}),
        ),
    ]);
    for (name, value) in overrides {
        configs.insert(*name, value.clone());
    }
    for (name, value) in &configs {
        let path = snapshot.join(name);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, serde_json::to_vec(value).unwrap()).unwrap();
    }
    std::fs::copy(
        repo.join("native/ken-torch-backend/tests/fixtures/qwen/model.safetensors"),
        snapshot.join("model.safetensors"),
    )
    .unwrap();
    std::fs::copy(repo.join("crates/ken-models/tests/fixtures/context/valid/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/tokenizer.json"),snapshot.join("tokenizer.json")).unwrap();
    if let Some(weights) = weights {
        std::fs::write(snapshot.join("model.safetensors"), weights).unwrap();
    }
    let mut artifacts = BTreeMap::new();
    for name in configs
        .keys()
        .copied()
        .chain(["model.safetensors", "tokenizer.json"])
    {
        artifacts.insert(
            name,
            fingerprint(&std::fs::read(snapshot.join(name)).unwrap()),
        );
    }
    let model=TransformerModel::from_json(&json!({"name":"fixtures/CPU-Qwen","assets":{"model_id":"fixtures/CPU-Qwen","revision":revision,"license":"derived-tiny-test-fixture","artifacts":artifacts},"dimension":4,"architecture":"qwen3","weight_layout":"unprefixed","role":"encoder","configs":configs}).to_string()).unwrap();
    let source = ModelFileSource::new(&snapshot, temp.path()).unwrap();
    (temp, model, source, runtime)
}

pub(crate) fn fixture() -> (
    tempfile::TempDir,
    TransformerModel,
    ModelFileSource,
    NativeTransformerRuntime,
) {
    fixture_with_configs(&[])
}
