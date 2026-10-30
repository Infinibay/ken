//! Impact evidence. The existing native navigation owner supplies architecture
//! and test heuristics; this module owns only their union with reverse imports
//! and historical coupling.
use crate::{
    HistoryError, Result,
    cochange::{self, CochangeOptions},
    normalize,
};
use rusqlite::{Connection, OptionalExtension};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet, VecDeque},
    path::Path,
};

pub trait NavigationEvidence {
    fn architecture(&self, depth: i64, limit: i64) -> Result<Value>;
    fn find_tests(&self, path: &str, limit: i64) -> Result<Value>;
}
impl NavigationEvidence for ken_search::navigation::IndexNavigation {
    fn architecture(&self, depth: i64, limit: i64) -> Result<Value> {
        let value = ken_search::navigation::IndexNavigation::architecture(self, depth, limit)
            .map_err(|e| HistoryError::Navigation(e.to_string()))?;
        serde_json::to_value(value).map_err(|e| HistoryError::Navigation(e.to_string()))
    }
    fn find_tests(&self, path: &str, limit: i64) -> Result<Value> {
        let value = ken_search::navigation::IndexNavigation::find_tests(self, path, limit)
            .map_err(|e| HistoryError::Navigation(e.to_string()))?;
        serde_json::to_value(value).map_err(|e| HistoryError::Navigation(e.to_string()))
    }
}
pub fn architecture(navigation: &dyn NavigationEvidence, depth: i64, limit: i64) -> Result<Value> {
    navigation.architecture(depth, limit)
}
struct Evidence {
    path: String,
    hops: i64,
    channels: Vec<String>,
}
pub fn blast_radius(
    conn: &Connection,
    path: &str,
    max_hops: i64,
    navigation: &dyn NavigationEvidence,
    root: Option<&Path>,
    options: &CochangeOptions,
) -> Result<Value> {
    let target = normalize(path);
    let target_id: Option<i64> = conn
        .query_row("SELECT id FROM ci_files WHERE path=?", [&target], |r| {
            r.get(0)
        })
        .optional()?;
    let Some(target_id) = target_id else {
        return Ok(json!({"ok":false,"error":"file not indexed","path":target}));
    };
    let mut statement = conn.prepare("SELECT id,path FROM ci_files")?;
    let paths = statement
        .query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))?
        .collect::<rusqlite::Result<BTreeMap<_, _>>>()?;
    let mut statement = conn
        .prepare("SELECT from_file_id,to_file_id FROM ci_imports WHERE to_file_id IS NOT NULL")?;
    let mut reverse: BTreeMap<i64, BTreeSet<i64>> = BTreeMap::new();
    for row in statement.query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, i64>(1)?)))? {
        let (a, b) = row?;
        reverse.entry(b).or_default().insert(a);
    }
    let unresolved: i64 = conn.query_row(
        "SELECT COUNT(*) FROM ci_imports WHERE resolution='unresolved'",
        [],
        |r| r.get(0),
    )?;
    let internal: i64 = conn.query_row(
        "SELECT COUNT(*) FROM ci_imports WHERE to_file_id IS NOT NULL OR resolution='unresolved'",
        [],
        |r| r.get(0),
    )?;
    let mut queue = VecDeque::from([target_id]);
    let mut hops = BTreeMap::from([(target_id, 0i64)]);
    while let Some(id) = queue.pop_front() {
        let hop = hops[&id];
        if hop >= max_hops.max(1) {
            continue;
        }
        for &importer in reverse.get(&id).into_iter().flatten() {
            if let std::collections::btree_map::Entry::Vacant(entry) = hops.entry(importer) {
                entry.insert(hop + 1);
                queue.push_back(importer);
            }
        }
    }
    let mut evidence: BTreeMap<String, Evidence> = BTreeMap::new();
    for (id, hop) in hops {
        if id != target_id
            && let Some(path) = paths.get(&id).filter(|p| !p.is_empty())
        {
            evidence.insert(
                path.clone(),
                Evidence {
                    path: path.clone(),
                    hops: hop,
                    channels: vec![format!("imports(hop {hop})")],
                },
            );
        }
    }
    let tests = navigation.find_tests(&target, 50)?;
    for test in tests["tests"].as_array().into_iter().flatten() {
        if let (Some(path), Some(reason)) = (test["path"].as_str(), test["reason"].as_str()) {
            evidence
                .entry(path.into())
                .or_insert_with(|| Evidence {
                    path: path.into(),
                    hops: 1,
                    channels: Vec::new(),
                })
                .channels
                .push(format!("test-of ({reason})"));
        }
    }
    let mut co_options = options.clone();
    co_options.limit = 30;
    if let Ok(co) = cochange::cochange(conn, &target, root, &co_options) {
        for partner in co["partners"].as_array().into_iter().flatten() {
            if let (Some(path), Some(support)) =
                (partner["path"].as_str(), partner["support"].as_i64())
            {
                evidence
                    .entry(path.into())
                    .or_insert_with(|| Evidence {
                        path: path.into(),
                        hops: 1,
                        channels: Vec::new(),
                    })
                    .channels
                    .push(format!("co-changed {support}x"));
            }
        }
    }
    let mut results: Vec<_> = evidence.into_values().collect();
    results.sort_by(|a, b| {
        a.hops
            .cmp(&b.hops)
            .then_with(|| b.channels.len().cmp(&a.channels.len()))
            .then_with(|| a.path.cmp(&b.path))
    });
    let direct: Vec<_> = results
        .iter()
        .filter(|e| e.hops == 1 && e.channels.iter().any(|c| c.starts_with("imports")))
        .map(|e| e.path.clone())
        .collect();
    let impacted: Vec<_> = results
        .iter()
        .map(|e| json!({"path":e.path,"hops":e.hops,"evidence":e.channels}))
        .collect();
    Ok(
        json!({"ok":true,"path":target,"direct_importers":direct,"impacted":impacted,"coverage_note":format!("{unresolved}/{internal} internal imports are unresolved and not traced (external deps excluded) — this is a LOWER bound; verify before assuming safety")}),
    )
}
