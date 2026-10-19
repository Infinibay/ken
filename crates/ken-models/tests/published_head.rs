use ken_models::{RerankerModel, compile_head};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::path::PathBuf;

fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/ettin")
}
fn manifest() -> Value {
    serde_json::from_str(&std::fs::read_to_string(fixtures().join("manifest.json")).unwrap())
        .unwrap()
}

#[test]
fn published_head_matches_every_original_preparation_byte() {
    let data = manifest();
    let model = RerankerModel::from_json(&data["head"]["definition"].to_string()).unwrap();
    let source = model
        .source_assets()
        .verify(&fixtures().join(data["head"]["source"].as_str().unwrap()))
        .unwrap();
    let result = compile_head(&source).unwrap();
    assert_eq!(
        result,
        std::fs::read(fixtures().join("head/reference.onnx")).unwrap()
    );
}

#[test]
fn malformed_published_heads_return_errors() {
    let data = manifest();
    for (name, variant) in data["invalid"].as_object().unwrap() {
        if variant["kind"] != "head" {
            continue;
        }
        let model = RerankerModel::from_json(&variant["definition"].to_string()).unwrap();
        let source = model
            .source_assets()
            .verify(&fixtures().join(variant["source"].as_str().unwrap()))
            .unwrap();
        assert!(compile_head(&source).is_err(), "{name}");
    }
}

#[test]
fn real_ettin_assembly_matches_registered_graph_without_python_cache() {
    let path =
        std::env::var_os("KEN_ETTIN_SOURCE").expect("explicit prepared KEN_ETTIN_SOURCE required");
    let definition: Value = serde_json::from_str(include_str!(
        "../../../src/ken/embedder/data/ettin-68m-fp32.json"
    ))
    .unwrap();
    let model = RerankerModel::from_json(&definition.to_string()).unwrap();
    let source = model.source_assets().verify(&PathBuf::from(path)).unwrap();
    let result = compile_head(&source).unwrap();
    assert_eq!(result.len(), 274035078);
    assert_eq!(
        format!("{:x}", Sha256::digest(&result)),
        "8e22c1a014dbb6bf803824b531943ee067de4e9c6dea72f8c178348732db38bf"
    );
}

#[test]
fn corrupt_wire_is_bounded_and_never_panics() {
    let data = manifest();
    let definition = data["head"]["definition"].clone();
    let original = fixtures().join(data["head"]["source"].as_str().unwrap());
    let mut cases = vec![
        vec![0],
        vec![8, 128],
        vec![9, 0],
        vec![11, 12],
        vec![58, 3, 8],
        vec![58, 255, 255, 255, 255, 255, 255, 255, 255, 255, 127],
        vec![58, 0, 58, 0, 66, 2, 16, 18],
        vec![58, 4, 98, 0, 98, 0, 66, 2, 16, 18],
    ];
    cases.push([8u8, 0].repeat(1_000_001));
    for bytes in cases {
        let temp = tempfile::tempdir().unwrap();
        let source = temp.path().join("a".repeat(40));
        let mut changed = definition.clone();
        for name in definition["source"]["artifacts"]
            .as_object()
            .unwrap()
            .keys()
        {
            let path = source.join(name);
            std::fs::create_dir_all(path.parent().unwrap()).unwrap();
            std::fs::copy(original.join(name), path).unwrap();
        }
        std::fs::write(source.join("onnx/model.onnx"), &bytes).unwrap();
        changed["source"]["artifacts"]["onnx/model.onnx"] = serde_json::json!({"bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(&bytes))});
        let model = RerankerModel::from_json(&changed.to_string()).unwrap();
        let verified = model.source_assets().verify(&source).unwrap();
        let result = std::panic::catch_unwind(|| compile_head(&verified))
            .expect("malformed wire must return Result");
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("ONNX wire"));
    }
}

#[test]
fn compilation_keeps_owned_source_after_original_paths_change() {
    let data = manifest();
    let definition = data["head"]["definition"].clone();
    let model = RerankerModel::from_json(&definition.to_string()).unwrap();
    let original = fixtures().join(data["head"]["source"].as_str().unwrap());
    let temp = tempfile::tempdir().unwrap();
    let source = temp.path().join("a".repeat(40));
    for name in definition["source"]["artifacts"]
        .as_object()
        .unwrap()
        .keys()
    {
        let path = source.join(name);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::copy(original.join(name), path).unwrap();
    }
    let verified = model.source_assets().verify(&source).unwrap();
    std::fs::remove_dir_all(&source).unwrap();
    assert_eq!(
        compile_head(&verified).unwrap(),
        std::fs::read(fixtures().join("head/reference.onnx")).unwrap()
    );
}

#[test]
fn published_namespace_collision_is_an_explicit_error() {
    let data = manifest();
    let mut definition = data["head"]["definition"].clone();
    let original = fixtures().join(data["head"]["source"].as_str().unwrap());
    let temp = tempfile::tempdir().unwrap();
    let source = temp.path().join("a".repeat(40));
    for name in definition["source"]["artifacts"]
        .as_object()
        .unwrap()
        .keys()
    {
        let path = source.join(name);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::copy(original.join(name), path).unwrap();
    }
    let name = b"ken_published_head/existing";
    let mut node = vec![26, name.len() as u8];
    node.extend_from_slice(name);
    let value = b"\x0a\x06tokens";
    let mut graph = vec![10, node.len() as u8];
    graph.extend(node);
    graph.extend([98, value.len() as u8]);
    graph.extend(value);
    let mut bytes = vec![58, graph.len() as u8];
    bytes.extend(graph);
    bytes.extend([66, 2, 16, 18]);
    std::fs::write(source.join("onnx/model.onnx"), &bytes).unwrap();
    definition["source"]["artifacts"]["onnx/model.onnx"] =
        serde_json::json!({"bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(&bytes))});
    let model = RerankerModel::from_json(&definition.to_string()).unwrap();
    let verified = model.source_assets().verify(&source).unwrap();
    assert!(
        compile_head(&verified)
            .unwrap_err()
            .to_string()
            .contains("namespace collision")
    );
}
