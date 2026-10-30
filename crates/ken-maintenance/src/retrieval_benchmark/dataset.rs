//! Judgment admission owns shape/identity, independently of response quality.
use super::{hash, invalid};
use crate::Result;
use serde_json::Value;
use std::{collections::BTreeSet, path::Path};
pub struct Dataset {
    pub cases: Vec<Value>,
    pub sha256: String,
}
pub fn valid_path(value: &str) -> bool {
    if value.is_empty() || value.contains('\\') || value.starts_with('/') {
        return false;
    }
    if value == "." {
        return true;
    }
    value
        .split('/')
        .all(|part| !part.is_empty() && part != "." && part != "..")
}
pub(super) fn digest(value: &str, min: usize, max: usize) -> bool {
    (min..=max).contains(&value.len())
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn integer(value: &Value) -> Option<String> {
    let Value::Number(number) = value else {
        return None;
    };
    if let Some(value) = number.as_i64() {
        return (value >= 0).then(|| value.to_string());
    }
    if let Some(value) = number.as_u64() {
        return Some(value.to_string());
    }
    let spelling = number.to_string();
    (!spelling.is_empty() && spelling.bytes().all(|b| b.is_ascii_digit())).then_some(spelling)
}
pub(super) fn span(value: &Value) -> Result<()> {
    if !value.is_object() {
        return Err(invalid("span must be an object"));
    }
    let start = integer(&value["start_line"]).filter(|n| n != "0");
    let end = integer(&value["end_line"]);
    match (start, end) {
        (Some(start), Some(end)) if (start.len(), start.as_str()) <= (end.len(), end.as_str()) => {
            Ok(())
        }
        _ => Err(invalid("invalid inclusive source span")),
    }
}
pub(super) fn bounds(value: &Value) -> Result<(usize, usize)> {
    span(value)?;
    let start = value["start_line"]
        .as_u64()
        .and_then(|n| usize::try_from(n).ok())
        .ok_or_else(|| invalid("source span outside native source"))?;
    let end = value["end_line"]
        .as_u64()
        .and_then(|n| usize::try_from(n).ok())
        .ok_or_else(|| invalid("source span outside native source"))?;
    Ok((start, end))
}
pub fn validate_case(case: &Value) -> Result<()> {
    if !case.is_object() {
        return Err(invalid("case must be an object"));
    }
    for key in [
        "id",
        "repo_id",
        "repo_commit",
        "query",
        "language",
        "purpose",
        "behavior_group",
    ] {
        if !case[key]
            .as_str()
            .is_some_and(|s| s.chars().any(|c| !ken_text::unicode::whitespace(c)))
        {
            return Err(invalid(format!("{key} must be a nonempty string")));
        }
    }
    if !digest(case["repo_commit"].as_str().unwrap(), 40, 64) {
        return Err(invalid("repo_commit must be an immutable git revision"));
    }
    if !["en", "es"].contains(&case["language"].as_str().unwrap()) {
        return Err(invalid("language must be en or es"));
    }
    if ![
        "implementation",
        "identity",
        "usage",
        "tests",
        "documentation",
    ]
    .contains(&case["purpose"].as_str().unwrap())
    {
        return Err(invalid("unknown judgment purpose"));
    }
    let answerable = case["answerable"]
        .as_bool()
        .ok_or_else(|| invalid("answerable must be boolean"))?;
    let alternatives = case["alternatives"]
        .as_array()
        .filter(|a| a.is_empty() != answerable)
        .ok_or_else(|| {
            invalid("positive cases need alternatives; negative cases must have none")
        })?;
    for alternative in alternatives {
        if !alternative.is_object() || !alternative["path"].as_str().is_some_and(valid_path) {
            return Err(invalid("alternative path must be project relative"));
        }
        if !alternative["source_hash"]
            .as_str()
            .is_some_and(|s| digest(s, 64, 64))
        {
            return Err(invalid("source_hash must be SHA-256 of source bytes"));
        }
        let anchors = alternative["anchors"]
            .as_array()
            .filter(|a| !a.is_empty())
            .ok_or_else(|| invalid("alternative requires nonempty anchors"))?;
        for anchor in anchors {
            span(anchor)?;
        }
        if let Some(entity) = alternative.get("entity").filter(|v| !v.is_null()) {
            if !entity.is_object()
                || !["kind", "qualname"]
                    .iter()
                    .all(|k| entity[*k].as_str().is_some_and(|s| !s.is_empty()))
            {
                return Err(invalid("entity needs kind and qualname"));
            }
            if entity
                .get("owner")
                .is_some_and(|v| !v.is_null() && !v.is_string())
            {
                return Err(invalid("entity owner must be a name or null"));
            }
            if integer(&entity["definition_ordinal"]).is_none() {
                return Err(invalid("entity requires nonnegative definition_ordinal"));
            }
        }
    }
    Ok(())
}
pub fn load_dataset(path: &Path) -> Result<Dataset> {
    let content = std::fs::read(path)?;
    let decoded = std::str::from_utf8(&content).map_err(|e| invalid(e.to_string()))?;
    let mut cases = Vec::new();
    let mut ids = BTreeSet::new();
    for (index, line) in ken_text::unicode::splitlines(decoded)
        .into_iter()
        .enumerate()
    {
        if line.chars().all(ken_text::unicode::whitespace) {
            continue;
        }
        let case: Value = serde_json::from_str(line)
            .map_err(|error| invalid(format!("{}:{}: {error}", path.display(), index + 1)))?;
        validate_case(&case)
            .map_err(|error| invalid(format!("{}:{}: {error}", path.display(), index + 1)))?;
        let id = case["id"].as_str().unwrap().to_owned();
        if !ids.insert(id.clone()) {
            return Err(invalid(format!("duplicate case id: {id}")));
        }
        cases.push(case);
    }
    if cases.is_empty() {
        return Err(invalid("empty retrieval dataset"));
    }
    Ok(Dataset {
        cases,
        sha256: hash(&content),
    })
}
