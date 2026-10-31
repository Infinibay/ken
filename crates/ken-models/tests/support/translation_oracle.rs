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

/// Select a whole original by the actual float/int8 GEMM backend pair.
/// This pure selector does not discover or load a native runtime.
pub fn for_backend(
    os: &str,
    arch: &str,
    float_backend: &str,
    int8_backend: &str,
) -> Result<Value, String> {
    let missing = || {
        format!(
            "independent original translation oracle required for {os}/{arch} {float_backend}/{int8_backend}"
        )
    };
    let (platform, architecture) = match (os, arch) {
        ("linux", "x86_64") => ("Linux", "x86_64"),
        _ => return Err(missing()),
    };
    let registry: Value = serde_json::from_str(include_str!(
        "../fixtures/translation-reference-profiles.json"
    ))
    .map_err(|error| error.to_string())?;
    if registry["format"] != "ken-translation-reference-profiles/1" {
        return Err("invalid translation reference registry".into());
    }
    let profile = select_profile(
        &registry,
        platform,
        architecture,
        float_backend,
        int8_backend,
    )?;
    let name = profile["file"]
        .as_str()
        .ok_or("translation reference file missing")?;
    let relative = std::path::Path::new(name);
    if relative.components().count() != 1
        || !matches!(
            relative.components().next(),
            Some(std::path::Component::Normal(_))
        )
    {
        return Err("translation reference basename required".into());
    }
    let length = profile["artifact"]["bytes"]
        .as_u64()
        .filter(|length| *length > 0 && *length <= 16 * 1024 * 1024)
        .ok_or("translation reference size invalid")?;
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(relative);
    let mut raw = Vec::new();
    std::fs::File::open(path)
        .map_err(|error| error.to_string())?
        .take(length + 1)
        .read_to_end(&mut raw)
        .map_err(|error| error.to_string())?;
    if raw.len() as u64 != length
        || profile["artifact"]["sha256"] != format!("{:x}", Sha256::digest(&raw))
    {
        return Err("preserved translation reference bytes differ".into());
    }
    let mut decoded = String::new();
    flate2::read::GzDecoder::new(&raw[..])
        .read_to_string(&mut decoded)
        .map_err(|error| error.to_string())?;
    let value: Value = serde_json::from_str(&decoded).map_err(|error| error.to_string())?;
    let digest = profile["results_sha256"]
        .as_str()
        .ok_or("translation reference result digest missing")?;
    // The compressed SHA authenticates the entire document, including its
    // original whole-result digest. Never relabel or merge its histories.
    if value["format"] != "ken-translation-oracle/1"
        || value["platform"] != platform
        || value["architecture"] != architecture
        || value["results_sha256"] != digest
    {
        return Err("preserved translation reference profile differs".into());
    }
    Ok(value)
}

/// A single original cannot certify two different numerical profiles.
pub fn select_profile<'a>(
    registry: &'a Value,
    platform: &str,
    architecture: &str,
    float_backend: &str,
    int8_backend: &str,
) -> Result<&'a Value, String> {
    use std::collections::HashSet;
    let profiles = registry["profiles"]
        .as_array()
        .ok_or("translation reference profiles missing")?;
    let fields = ["platform", "architecture", "float_backend", "int8_backend"];
    let mut keys = HashSet::new();
    let mut artifacts = HashSet::new();
    for row in profiles {
        let key = fields
            .iter()
            .map(|field| {
                row[field]
                    .as_str()
                    .filter(|value| !value.is_empty())
                    .ok_or("invalid translation reference profile")
            })
            .collect::<Result<Vec<_>, _>>()?;
        let sha = row["artifact"]["sha256"]
            .as_str()
            .filter(|value| {
                value.len() == 64
                    && value
                        .bytes()
                        .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
            })
            .ok_or("invalid translation reference artifact digest")?;
        if !keys.insert(key) || !artifacts.insert(sha) {
            return Err("duplicate translation reference profile or shared observations".into());
        }
    }
    profiles.iter().find(|row| {
        row["platform"] == platform && row["architecture"] == architecture
            && row["float_backend"] == float_backend && row["int8_backend"] == int8_backend
    }).ok_or_else(|| format!(
        "independent original translation oracle required for {platform}/{architecture} {float_backend}/{int8_backend}"
    ))
}

pub fn for_host(os: &str, arch: &str) -> Value {
    if (os, arch) == ("linux", "x86_64") {
        let (registration, module, core) =
            native_declaration().expect("prepare the registered CT2 CPU module");
        let runtime =
            ken_models::NativeTranslationRuntime::from_json(&registration, &module, &core)
                .expect("authenticated native translation declaration");
        let actual = runtime.load().expect("actual native translation backend");
        return for_backend(os, arch, &actual.float_backend, &actual.int8_backend)
            .unwrap_or_else(|error| panic!("{error}"));
    }
    let (platform, architecture) = match (os, arch) {
        ("linux", "aarch64") => ("Linux", "aarch64"),
        ("macos", "aarch64") => ("Darwin", "arm64"),
        _ => panic!("independent original translation oracle required for {os}/{arch}"),
    };
    let document: Value = serde_json::from_slice(&fixture_json::decode(include_bytes!(
        "../fixtures/portable/translation-reference.json.gz"
    )))
    .unwrap();
    let value = document["oracles"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["platform"] == platform && row["architecture"] == architecture)
        .expect("one local original translation oracle")
        .clone();
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
