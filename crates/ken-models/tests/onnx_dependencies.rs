use ken_models::{ModelAssets, ModelFileSource, verify_onnx_dependencies};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::fs;

fn varint(mut value: u64) -> Vec<u8> {
    let mut out = Vec::new();
    while value >= 128 {
        out.push((value as u8 & 127) | 128);
        value >>= 7;
    }
    out.push(value as u8);
    out
}
fn bytes(tag: u64, value: &[u8]) -> Vec<u8> {
    let mut out = varint(tag * 8 + 2);
    out.extend(varint(value.len() as u64));
    out.extend(value);
    out
}
fn tensor(entries: &[(&str, &str)]) -> Vec<u8> {
    let mut out = vec![8, 3, 16, 2, 112, 1]; // dims[3], UINT8, EXTERNAL.
    for (key, value) in entries {
        let mut entry = bytes(1, key.as_bytes());
        entry.extend(bytes(2, value.as_bytes()));
        out.extend(bytes(13, &entry));
    }
    out
}
fn validate(graph: &[u8]) -> bool {
    let temp = tempfile::tempdir().unwrap();
    let snapshot = temp.path().join("1111111111111111111111111111111111111111");
    let private = temp.path().join("private");
    fs::create_dir_all(snapshot.join("onnx")).unwrap();
    fs::create_dir(&private).unwrap();
    fs::write(snapshot.join("onnx/model.onnx"), graph).unwrap();
    fs::write(snapshot.join("onnx/weights.bin"), b"abc").unwrap();
    let declaration = json!({"model_id":"test/dependencies","revision":"1111111111111111111111111111111111111111","artifacts":{
        "onnx/model.onnx":{"bytes":graph.len(),"sha256":format!("{:x}",Sha256::digest(graph))},
        "onnx/weights.bin":{"bytes":3,"sha256":"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"}}});
    let assets = ModelAssets::from_json(&declaration.to_string()).unwrap();
    let source = ModelFileSource::new(&snapshot, &private).unwrap();
    let files = assets.verify_files(&source).unwrap();
    verify_onnx_dependencies("onnx/model.onnx", &files).is_ok()
}

#[test]
fn registered_graph_relative_file_ranges_are_validated() {
    let graph = bytes(
        7,
        &bytes(
            5,
            &tensor(&[
                ("location", "weights.bin"),
                ("offset", "0"),
                ("length", "3"),
            ]),
        ),
    );
    assert!(validate(&graph));
    let outside = bytes(
        7,
        &bytes(
            5,
            &tensor(&[
                ("location", "weights.bin"),
                ("offset", "2"),
                ("length", "2"),
            ]),
        ),
    );
    assert!(!validate(&outside));
}

#[test]
fn nested_external_references_cannot_escape_owned_artifacts() {
    for location in [
        "/tmp/outside",
        "../weights.bin",
        "nested/../../weights.bin",
        "unknown.bin",
    ] {
        let value = tensor(&[("location", location)]);
        let direct = bytes(7, &bytes(5, &value));
        let attribute = bytes(7, &bytes(1, &bytes(5, &bytes(5, &value))));
        assert!(!validate(&direct), "{location}");
        assert!(!validate(&attribute), "nested {location}");
    }
}

#[test]
fn every_tensor_carrier_is_audited() {
    for location in ["weights.bin", "../weights.bin"] {
        let tensor = tensor(&[("location", location), ("length", "3")]);
        let sparse = [bytes(1, &tensor), bytes(2, &tensor)].concat();
        let inner_graph = bytes(5, &tensor);
        let mut models = vec![bytes(7, &bytes(5, &tensor)), bytes(7, &bytes(15, &sparse))];
        for (field, payload) in [
            (5, &tensor),
            (6, &inner_graph),
            (10, &tensor),
            (11, &inner_graph),
            (22, &sparse),
            (23, &sparse),
        ] {
            let attribute = bytes(field, payload);
            models.push(bytes(7, &bytes(1, &bytes(5, &attribute))));
            models.push(bytes(25, &bytes(11, &attribute)));
            models.push(bytes(25, &bytes(7, &bytes(5, &attribute))));
        }
        for field in [1, 2] {
            models.push(bytes(20, &bytes(field, &inner_graph)));
        }
        for model in models {
            assert_eq!(validate(&model), location == "weights.bin");
        }
    }
}

#[test]
fn ambiguous_external_metadata_and_invalid_ranges_are_rejected() {
    let entries = [
        vec![("offset", "0")],
        vec![("location", "weights.bin"), ("location", "weights.bin")],
        vec![("location", "weights.bin"), ("basepath", "/tmp")],
        vec![("location", "weights.bin"), ("offset", "-1")],
        vec![("location", "weights.bin"), ("length", "-1")],
        vec![
            ("location", "weights.bin"),
            ("offset", "18446744073709551616"),
        ],
        vec![
            ("location", "weights.bin"),
            ("offset", "18446744073709551615"),
            ("length", "2"),
        ],
        vec![("location", "weights.bin"), ("offset", "4")],
        vec![("location", "weights.bin"), ("length", "4")],
    ];
    for entries in entries {
        assert!(
            !validate(&bytes(7, &bytes(5, &tensor(&entries)))),
            "{entries:?}"
        );
    }
}

#[test]
fn malformed_wire_and_structural_budgets_are_rejected() {
    for malformed in [
        vec![0],
        vec![58, 128],
        vec![58, 4, 1],
        vec![255; 11],
        vec![59],
    ] {
        assert!(!validate(&malformed));
    }
    let mut graph = bytes(5, &tensor(&[("location", "weights.bin")]));
    for _ in 0..65 {
        graph = bytes(1, &bytes(5, &bytes(6, &graph)));
    }
    assert!(!validate(&bytes(7, &graph)));
    let mut fields = Vec::new();
    for _ in 0..1_000_001 {
        fields.extend_from_slice(&[8, 0]);
    }
    assert!(!validate(&fields));
    // A length-prefixed string cannot allocate its claimed multi-GiB size.
    let mut oversized = vec![10];
    oversized.extend(varint(u64::MAX));
    assert!(!validate(&bytes(7, &bytes(5, &bytes(13, &oversized)))));
}
