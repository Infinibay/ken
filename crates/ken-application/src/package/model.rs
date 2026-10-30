use serde::{Deserialize, Serialize};
use std::{collections::BTreeMap, path::PathBuf};
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Target {
    pub os: String,
    pub arch: String,
    pub device: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FileRecord {
    pub bytes: u64,
    pub sha256: String,
    pub mode: u32,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub format: String,
    pub target: Target,
    pub entrypoints: BTreeMap<String, String>,
    pub resources: String,
    pub files: BTreeMap<String, FileRecord>,
    pub provenance: serde_json::Value,
}
#[derive(Clone, Debug, Serialize)]
pub struct PackageInfo {
    pub manifest_sha256: String,
    pub target: Target,
    pub entrypoints: BTreeMap<String, String>,
    pub resources: String,
    pub provenance: serde_json::Value,
    pub file_count: usize,
    pub total_bytes: u64,
}
#[derive(Debug, Serialize)]
pub struct PackageReport {
    pub action: String,
    pub executable: PathBuf,
    pub resources: PathBuf,
    pub release_root: PathBuf,
    pub current_release: String,
    pub previous_release: Option<String>,
    pub provenance: serde_json::Value,
}
#[derive(Debug, Serialize)]
pub struct PackageStatus {
    pub current_release: Option<String>,
    pub previous_release: Option<String>,
    pub executable: Option<PathBuf>,
    pub resources: Option<PathBuf>,
    pub release_root: Option<PathBuf>,
}
#[derive(Clone, Copy, Debug, Serialize)]
#[serde(tag = "phase", rename_all = "snake_case")]
pub enum PackageEvent {
    StagingCopied,
    ReleasePublished,
    ActivationPrepared,
    Activated,
}
