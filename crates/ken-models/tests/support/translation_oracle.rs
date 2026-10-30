//! Test-only selection of independent original translation observations.
#![allow(dead_code)]
#[path = "fixture_json.rs"]
mod fixture_json;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::io::Read;

pub fn native_declaration() -> Option<(String, std::path::PathBuf, std::path::PathBuf)> {
    if !cfg!(all(target_os = "linux", target_arch = "x86_64")) {
        return None;
    }
    let path =
        std::env::var_os("KEN_CT2_PREPARATION").expect("prepare the registered CT2 CPU module");
    let value: Value = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    Some((
        value["registration"].to_string(),
        value["module_path"].as_str().unwrap().into(),
        value["core_root"].as_str().unwrap().into(),
    ))
}

pub fn for_host(os: &str, arch: &str) -> Value {
    let (platform, architecture) = match (os, arch) {
        ("linux", "x86_64") => ("Linux", "x86_64"),
        ("linux", "aarch64") => ("Linux", "aarch64"),
        ("macos", "aarch64") => ("Darwin", "arm64"),
        _ => panic!("independent original translation oracle required for {os}/{arch}"),
    };
    let value: Value = if arch == "x86_64" {
        let raw = include_bytes!("../fixtures/translation-linux-x86_64.json.gz");
        assert_eq!(raw.len(), 12338);
        assert_eq!(
            format!("{:x}", Sha256::digest(raw)),
            "97815693b2aef5441f887685623025260360fdfb6c8d888637f8b1582b7a7f00"
        );
        let mut decoded = String::new();
        flate2::read::GzDecoder::new(&raw[..])
            .read_to_string(&mut decoded)
            .unwrap();
        serde_json::from_str(&decoded).unwrap()
    } else {
        let document: Value = serde_json::from_slice(&fixture_json::decode(include_bytes!(
            "../fixtures/portable/translation-reference.json.gz"
        )))
        .unwrap();
        document["oracles"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| row["platform"] == platform && row["architecture"] == architecture)
            .expect("one local original translation oracle")
            .clone()
    };
    assert_eq!(value["platform"], platform);
    assert_eq!(value["architecture"], architecture);
    value
}

pub fn raw_histories(os: &str, arch: &str) -> Vec<Value> {
    if (os, arch) == ("linux", "x86_64") {
        let original = for_host(os, arch);
        let mut rows = Vec::new();
        for row in original["results"].as_array().unwrap() {
            for call in row["calls"].as_array().unwrap() {
                let trace = &call["trace"];
                if !trace["prepared"].is_string() {
                    continue;
                }
                let mut raw = json!({"input":trace["prepared"],"source_ids":trace["source_ids"],
                    "source_pieces_with_eos":trace["source_pieces_with_eos"]});
                if trace["hypotheses"].is_array() {
                    raw["hypotheses"] = trace["hypotheses"].clone();
                    raw["decoded"] = trace["decoded"].clone();
                } else {
                    assert_eq!(call["error"]["type"], "RuntimeError");
                    raw["error"] = call["error"]["message"].clone();
                }
                rows.push(raw);
            }
        }
        assert!(!rows.is_empty());
        rows
    } else {
        let platform = match (os, arch) {
            ("linux", "aarch64") => "Linux",
            ("macos", "aarch64") => "Darwin",
            _ => panic!("independent original raw translation oracle required for {os}/{arch}"),
        };
        let document: Value = serde_json::from_slice(&fixture_json::decode(include_bytes!(
            "../fixtures/portable/translation-raw-reference.json.gz"
        )))
        .unwrap();
        document["oracles"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| row["platform"] == platform)
            .unwrap()["original"]["results"]
            .as_array()
            .unwrap()
            .clone()
    }
}
