//! Test-only original-reference policy; production numerical operations are unchanged.
#![allow(dead_code)]
#[path = "x86_features.rs"]
mod capabilities;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    fs,
    io::Read,
    path::{Component, Path},
};
pub const INDEX: &str = include_str!("../fixtures/execution-profiles/index.json");
pub struct Reference {
    pub id: String,
    pub encoding: String,
    pub bytes: Vec<u8>,
}
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub fn context_descriptor() -> Value {
    let caps: Value =
        serde_json::from_str(&capabilities::json()).expect("native capability schema");
    json!({"format":"ken-context-profile/1","target":"linux-x86_64","features":caps["features"],"native_core_sha256":"c450a686085f441803ef914fc7e68bd417452e34ba5573344dc3dd40c0c71896","onnxruntime":"1.25.1","tokenizers":"0.22.2"})
}
fn canonical(value: &Value) -> String {
    match value {
        Value::Object(map) => {
            let mut keys = map.keys().collect::<Vec<_>>();
            keys.sort();
            format!(
                "{{{}}}",
                keys.into_iter()
                    .map(|key| format!(
                        "{}:{}",
                        serde_json::to_string(key).expect("JSON key"),
                        canonical(&map[key])
                    ))
                    .collect::<Vec<_>>()
                    .join(",")
            )
        }
        Value::Array(values) => format!(
            "[{}]",
            values.iter().map(canonical).collect::<Vec<_>>().join(",")
        ),
        _ => value.to_string(),
    }
}
pub fn registered(kind: &str, descriptor: &Value, repo: &Path) -> Result<Reference, String> {
    let index: Value = serde_json::from_str(INDEX).map_err(|e| e.to_string())?;
    select(&index, kind, descriptor, repo)
}
pub fn select(
    index: &Value,
    kind: &str,
    descriptor: &Value,
    repo: &Path,
) -> Result<Reference, String> {
    if index["format"] != "ken-execution-reference-registry/1" {
        return Err("invalid execution-reference registry".into());
    }
    let entries = index["families"][kind]
        .as_array()
        .ok_or("unknown reference family")?;
    let rows = entries
        .iter()
        .filter(|entry| entry["descriptor"] == *descriptor)
        .collect::<Vec<_>>();
    if rows.len() != 1 {
        return Err(format!(
            "unregistered or ambiguous {kind} execution profile: {descriptor}"
        ));
    }
    let entry = rows[0];
    let id = format!("{:x}", Sha256::digest(canonical(descriptor).as_bytes()));
    if entry["id"] != id {
        return Err("execution descriptor identity differs".into());
    }
    let resource = &entry["reference"];
    let relative = Path::new(resource["path"].as_str().ok_or("reference path missing")?);
    if relative.as_os_str().is_empty()
        || !relative
            .components()
            .all(|c| matches!(c, Component::Normal(_)))
    {
        return Err("unsafe reference path".into());
    }
    let length = resource["bytes"]
        .as_u64()
        .filter(|n| *n <= 16 * 1024 * 1024)
        .ok_or("reference size invalid")?;
    let mut bytes = Vec::new();
    fs::File::open(repo.join(relative))
        .map_err(|e| e.to_string())?
        .take(length + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    if bytes.len() as u64 != length || resource["sha256"] != format!("{:x}", Sha256::digest(&bytes))
    {
        return Err("preserved execution-reference bytes differ".into());
    }
    let encoding = resource["encoding"]
        .as_str()
        .filter(|s| matches!(*s, "json" | "gzip"))
        .ok_or("reference encoding invalid")?
        .to_owned();
    Ok(Reference {
        id,
        encoding,
        bytes,
    })
}
