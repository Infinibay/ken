//! Dataset isolation and one-use reserve admission, before any live producer.
use super::{
    dataset::{bounds, digest},
    hash, invalid, valid_path, validate_case,
};
use crate::Result;
use serde_json::Value;
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
fn normalized(query: &str) -> String {
    ken_text::unicode::casefold(query)
        .split(ken_text::unicode::whitespace)
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}
pub fn validate_partitions(development: &[Value], reserve: &[Value]) -> Result<()> {
    for (field, label) in [("repo_id", "repository"), ("behavior_group", "behavior")] {
        let left = development.iter().map(|c| &c[field]).collect::<Vec<_>>();
        if reserve.iter().any(|c| left.contains(&&c[field])) {
            return Err(invalid(format!(
                "{label} leakage between development and acceptance"
            )));
        }
    }
    let left = development
        .iter()
        .map(|c| normalized(c["query"].as_str().unwrap_or("")))
        .collect::<BTreeSet<_>>();
    if reserve
        .iter()
        .any(|c| left.contains(&normalized(c["query"].as_str().unwrap_or(""))))
    {
        return Err(invalid("query leakage between development and acceptance"));
    }
    Ok(())
}
fn over_budget(anchors: &[Value]) -> bool {
    let mut spans = Vec::new();
    for anchor in anchors {
        let Ok((start, end)) = bounds(anchor) else {
            return true;
        };
        spans.push((start, end));
    }
    spans.sort_unstable();
    let (mut count, mut current) = (0usize, None::<(usize, usize)>);
    for (start, end) in spans {
        match current {
            Some((a, b)) if start <= b.saturating_add(1) => current = Some((a, b.max(end))),
            Some((a, b)) => {
                count = count.saturating_add(b - a + 1);
                current = Some((start, end));
            }
            None => current = Some((start, end)),
        }
        if count > 40 {
            return true;
        }
    }
    if let Some((a, b)) = current {
        count = count.saturating_add(b - a + 1);
    }
    count > 40
}
pub fn acceptance_failures(cases: &[Value]) -> Result<Vec<String>> {
    for case in cases {
        validate_case(case)?;
    }
    let positive = cases
        .iter()
        .filter(|c| c["answerable"] == true)
        .collect::<Vec<_>>();
    let mut failures = Vec::new();
    if positive.len() != 300 {
        failures.push(format!(
            "acceptance requires 300 positives, received {}",
            positive.len()
        ));
    }
    let mut repos = BTreeMap::<&str, usize>::new();
    let mut languages = BTreeMap::<&str, usize>::new();
    let mut purposes = BTreeMap::<&str, usize>::new();
    for case in &positive {
        *repos.entry(case["repo_id"].as_str().unwrap()).or_default() += 1;
        *languages
            .entry(case["language"].as_str().unwrap())
            .or_default() += 1;
        *purposes
            .entry(case["purpose"].as_str().unwrap())
            .or_default() += 1;
    }
    if repos.len() != 12 || repos.values().any(|n| *n != 25) {
        failures.push("acceptance requires 12 repositories with 25 positives each".into());
    }
    if languages != BTreeMap::from([("en", 180), ("es", 120)]) {
        failures.push("acceptance requires 180 EN and 120 ES positives".into());
    }
    let n = |purpose: &str| purposes.get(purpose).copied().unwrap_or(0);
    if n("implementation") != 210
        || n("identity") != 45
        || n("usage") + n("tests") + n("documentation") != 45
    {
        failures.push("acceptance purpose quotas must be 210/45/45".into());
    }
    if cases.len() - positive.len() < 60 {
        failures.push("acceptance requires at least 60 separate negatives".into());
    }
    let queries = cases
        .iter()
        .map(|c| normalized(c["query"].as_str().unwrap()))
        .collect::<BTreeSet<_>>();
    if queries.len() != cases.len() {
        failures.push("duplicate query in acceptance".into());
    }
    let mut commits = BTreeMap::<&str, BTreeSet<&str>>::new();
    for case in cases {
        commits
            .entry(case["repo_id"].as_str().unwrap())
            .or_default()
            .insert(case["repo_commit"].as_str().unwrap());
    }
    for (repo, commits) in commits {
        if commits.len() != 1 {
            failures.push(format!("mixed source commits for {repo}"));
        }
    }
    for case in positive {
        for alternative in case["alternatives"].as_array().unwrap() {
            if over_budget(alternative["anchors"].as_array().unwrap()) {
                failures.push(format!(
                    "reference exceeds visible line budget: {}",
                    case["id"].as_str().unwrap()
                ));
            }
        }
    }
    Ok(failures)
}
pub fn verify_files(root: &Path, expected: &BTreeMap<String, String>) -> Result<()> {
    let canonical = root.canonicalize()?;
    for (path, digest) in expected {
        if !valid_path(path) {
            return Err(invalid("invalid frozen artifact path"));
        }
        let source = root.join(path).canonicalize()?;
        if !source.starts_with(&canonical) {
            return Err(invalid("invalid frozen artifact path"));
        }
        if hash(&std::fs::read(source)?) != *digest {
            return Err(invalid(format!("frozen artifact mismatch: {path}")));
        }
    }
    Ok(())
}
pub fn claim_reserve(registry: &Path, dataset: &str, engine: &str, profile: &str) -> Result<()> {
    if [dataset, engine, profile]
        .iter()
        .any(|s| !digest(s, 64, 64))
    {
        return Err(invalid("SHA256 receipt required"));
    }
    let parent = registry
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    std::fs::create_dir_all(parent)?;
    let conn = rusqlite::Connection::open(registry)?;
    conn.busy_timeout(Duration::from_secs(5))?;
    conn.execute_batch("CREATE TABLE IF NOT EXISTS attempts(dataset_sha256 TEXT PRIMARY KEY,engine_sha256 TEXT,profile_sha256 TEXT,created_at TEXT)")?;
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|e| invalid(e.to_string()))?;
    let date: String = conn.query_row(
        "SELECT strftime('%Y-%m-%dT%H:%M:%S',?,'unixepoch')",
        [now.as_secs().to_string()],
        |r| r.get(0),
    )?;
    let timestamp = format!("{date}.{:06}+00:00", now.subsec_micros());
    match conn.execute(
        "INSERT INTO attempts VALUES(?,?,?,?)",
        rusqlite::params![dataset, engine, profile, timestamp],
    ) {
        Ok(_) => Ok(()),
        Err(rusqlite::Error::SqliteFailure(error, _))
            if error.code == rusqlite::ErrorCode::ConstraintViolation =>
        {
            Err(invalid(
                "reserve has already been consumed; curate a new independent reserve",
            ))
        }
        Err(error) => Err(error.into()),
    }
}
