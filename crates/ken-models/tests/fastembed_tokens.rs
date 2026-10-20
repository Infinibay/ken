use ken_models::{FastEmbedInput, FastEmbedModel, ModelFileSource};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{fs, path::Path};

fn setup(
    root: &Path,
    config: &str,
    specials: &str,
    padding: bool,
) -> (FastEmbedModel, ModelFileSource) {
    let snapshot = root.join("1111111111111111111111111111111111111111");
    let private = root.join("private");
    fs::create_dir(&snapshot).unwrap();
    fs::create_dir(&private).unwrap();
    let mut tokenizer = json!({"version":"1.0","truncation":{"direction":"Left","max_length":3,"strategy":"LongestFirst","stride":1},
        "padding":null,"added_tokens":[],"normalizer":{"type":"Lowercase"},
        "pre_tokenizer":{"type":"Whitespace"},"post_processor":null,"decoder":null,
        "model":{"type":"WordLevel","vocab":{"[UNK]":0,"[PAD]":1,"a":2,"b":3},"unk_token":"[UNK]"}});
    if padding {
        tokenizer["padding"] = json!({"strategy":{"Fixed":5},"direction":"Right","pad_to_multiple_of":null,"pad_id":1,"pad_type_id":0,"pad_token":"[PAD]"});
    }
    let tokenizer = tokenizer.to_string();
    let files = [
        ("tokenizer.json", tokenizer.as_bytes()),
        ("config.json", b"{\"pad_token_id\":1}".as_slice()),
        ("tokenizer_config.json", config.as_bytes()),
        ("special_tokens_map.json", specials.as_bytes()),
    ];
    let mut artifacts = serde_json::Map::new();
    for (name, bytes) in files {
        fs::write(snapshot.join(name), bytes).unwrap();
        artifacts.insert(
            name.to_string(),
            json!({"bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(bytes))}),
        );
    }
    // Intentionally absent: lexical preparation must not read this weight file.
    artifacts.insert("model.onnx".into(),json!({"bytes":3,"sha256":"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"}));
    let model = FastEmbedModel::from_json(&json!({"format":"ken-fastembed-model/1","name":"test/tokens",
        "assets":{"model_id":"test/tokens","revision":"1111111111111111111111111111111111111111","artifacts":artifacts},
        "graph":"model.onnx","dimension":2,"pooling":"mean","task_id":null,"advisories":[]}).to_string()).unwrap();
    (model, ModelFileSource::new(&snapshot, &private).unwrap())
}

#[test]
fn config_bounds_override_old_truncation_without_loading_weights() {
    let temp = tempfile::tempdir().unwrap();
    let (model, source) = setup(
        temp.path(),
        r#"{"model_max_length":1000000000000000019884624838656,"max_length":4,"pad_token":"[PAD]"}"#,
        "{}",
        false,
    );
    let tokenizer = model.tokenizer(&source).unwrap();
    let rows = tokenizer
        .tokenize(&["a b b a b a"], FastEmbedInput::Passage)
        .unwrap();
    assert_eq!(rows[0].shape, [1, 4]);
    assert_eq!(rows[0].ids, vec![2, 3, 3, 2]);
    assert_eq!(rows[0].attention_mask, vec![1; 4]);
    assert!(model.assets().verify_files(&source).is_err());
    assert_eq!(
        fs::read_dir(temp.path().join("private")).unwrap().count(),
        0
    );
}

#[test]
fn existing_fixed_padding_and_special_insertion_order_are_preserved() {
    let temp = tempfile::tempdir().unwrap();
    let (model, source) = setup(
        temp.path(),
        r#"{"model_max_length":8,"pad_token":"[PAD]"}"#,
        r#"{"z":"<ZED>","a":{"content":"<ALPHA>"},"ignored":["<IGNORED>"],"number":1.5}"#,
        true,
    );
    let tokenizer = model.tokenizer(&source).unwrap();
    let rows = tokenizer
        .tokenize(&["<ZED> <ALPHA> <alpha>"], FastEmbedInput::Passage)
        .unwrap();
    assert_eq!(rows[0].shape, [1, 5]);
    assert_eq!(rows[0].ids, vec![4, 5, 5, 1, 1]);
    assert_eq!(rows[0].attention_mask, vec![1, 1, 1, 0, 0]);
    let lower = tokenizer
        .tokenize(&["<zed>"], FastEmbedInput::Passage)
        .unwrap();
    assert_eq!(lower[0].ids, vec![0, 0, 0, 1, 1]);
}

#[test]
fn texts_are_chunked_before_padding_and_empty_batches_stay_empty() {
    let temp = tempfile::tempdir().unwrap();
    let (model, source) = setup(
        temp.path(),
        r#"{"max_length":4,"pad_token":"[PAD]"}"#,
        "{}",
        false,
    );
    let tokenizer = model.tokenizer(&source).unwrap();
    assert!(
        tokenizer
            .tokenize(&[], FastEmbedInput::Query)
            .unwrap()
            .is_empty()
    );
    let mut texts = vec!["a"; 256];
    texts.push("a b b a b a");
    let rows = tokenizer.tokenize(&texts, FastEmbedInput::Passage).unwrap();
    assert_eq!(rows.len(), 2);
    assert_eq!(rows[0].shape, [256, 1]);
    assert_eq!(rows[1].shape, [1, 4]);
    assert_eq!(rows[0].ids, vec![2; 256]);
    assert_eq!(rows[1].ids, vec![2, 3, 3, 2]);
}

#[test]
fn malformed_config_types_and_selected_limits_are_rejected() {
    for config in [
        r#"{"pad_token":"[PAD]"}"#,
        r#"{"max_length":0,"pad_token":"[PAD]"}"#,
        r#"{"max_length":true,"pad_token":"[PAD]"}"#,
        r#"{"max_length":4.0,"pad_token":"[PAD]"}"#,
        r#"{"max_length":-1,"pad_token":"[PAD]"}"#,
        r#"{"max_length":4,"pad_token":{}}"#,
        r#"{"model_max_length":1000000000000000019884624838656,"pad_token":"[PAD]"}"#,
    ] {
        let temp = tempfile::tempdir().unwrap();
        let (model, source) = setup(temp.path(), config, "{}", false);
        assert!(model.tokenizer(&source).is_err(), "{config}");
    }
}

#[test]
fn ambiguous_special_dictionary_fields_are_rejected() {
    let temp = tempfile::tempdir().unwrap();
    let (model, source) = setup(
        temp.path(),
        r#"{"max_length":4,"pad_token":"[PAD]"}"#,
        r#"{"token":{"content":"one","content":"two"}}"#,
        false,
    );
    assert!(model.tokenizer(&source).is_err());
}

#[test]
fn unselected_huge_numeric_bounds_and_ignored_special_values_need_no_float_conversion() {
    let temp = tempfile::tempdir().unwrap();
    let (model, source) = setup(
        temp.path(),
        r#"{"model_max_length":1e400,"max_length":4,"pad_token":"[PAD]"}"#,
        r#"{"ignored":1e400,"token":"<TOKEN>"}"#,
        false,
    );
    let tokenizer = model.tokenizer(&source).unwrap();
    let batch = tokenizer
        .tokenize(&["<TOKEN>"], FastEmbedInput::Query)
        .unwrap();
    assert_eq!(batch[0].ids, vec![4]);
}

#[test]
fn tokenizer_can_use_owned_verified_files_after_source_removal() {
    let temp = tempfile::tempdir().unwrap();
    let (model, source) = setup(
        temp.path(),
        r#"{"max_length":4,"pad_token":"[PAD]"}"#,
        "{}",
        false,
    );
    let snapshot = temp.path().join(model.source_revision());
    fs::write(snapshot.join("model.onnx"), b"abc").unwrap();
    let files = model.assets().verify_files(&source).unwrap();
    fs::remove_dir_all(snapshot).unwrap();
    let tokenizer = model.tokenizer_from_files(&files).unwrap();
    assert_eq!(
        tokenizer.tokenize(&["a b"], FastEmbedInput::Query).unwrap()[0].ids,
        vec![2, 3]
    );
    let mut assets = serde_json::to_value(model.assets()).unwrap();
    assets["artifacts"]["config.json"]["sha256"] = json!("0".repeat(64));
    let other = FastEmbedModel::from_json(&json!({"format":"ken-fastembed-model/1","name":model.name(),
        "assets":assets,"graph":"model.onnx","dimension":2,"pooling":"mean","task_id":null,"advisories":[]}).to_string()).unwrap();
    assert!(other.tokenizer_from_files(&files).is_err());
}
