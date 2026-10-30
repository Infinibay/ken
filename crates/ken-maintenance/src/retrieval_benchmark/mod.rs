//! Strict grading of frozen retrieval responses; no search/model execution.
mod dataset;
mod protocol;
mod scoring;
use crate::{Error, Result};
pub use dataset::{Dataset, load_dataset, valid_path, validate_case};
pub use protocol::{acceptance_failures, claim_reserve, validate_partitions, verify_files};
pub use scoring::{check_gate, evaluate, request_for_case};
use serde_json::Value;
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
};
fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
fn hash(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    format!("{:x}", Sha256::digest(bytes))
}
pub fn evaluate_files(
    dataset: &Path,
    roots: &Path,
    responses: &Path,
    gate: Option<&Path>,
) -> Result<(Value, u8)> {
    let dataset = load_dataset(dataset)?;
    let roots: BTreeMap<String, PathBuf> = serde_json::from_slice(&std::fs::read(roots)?)?;
    let content = std::fs::read_to_string(responses)?;
    let responses = ken_text::unicode::splitlines(&content)
        .into_iter()
        .filter(|s| !s.trim_matches(ken_text::unicode::whitespace).is_empty())
        .map(serde_json::from_str)
        .collect::<std::result::Result<Vec<Value>, _>>()?;
    let mut report = evaluate(&dataset.cases, &responses, &roots)?;
    report["dataset_sha256"] = serde_json::json!(dataset.sha256);
    let failures = if let Some(path) = gate {
        let policy = serde_json::from_slice(&std::fs::read(path)?)?;
        let mut failures = check_gate(&report, Some(&policy))?;
        failures.extend(acceptance_failures(&dataset.cases)?);
        failures
    } else {
        Vec::new()
    };
    let status = u8::from(!failures.is_empty());
    report["failures"] = serde_json::json!(failures);
    Ok((report, status))
}
