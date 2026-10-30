//! Repository-scoped historical transactions and evidence-based coupling.
mod git;
use crate::{Result, normalize, positive_limit, rounded};
use rusqlite::{Connection, OptionalExtension, params};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, SystemTime, UNIX_EPOCH},
};

#[derive(Clone, Default)]
pub struct Cancellation(Arc<AtomicBool>);
impl Cancellation {
    pub fn cancel(&self) {
        self.0.store(true, Ordering::Release);
    }
    pub fn is_cancelled(&self) -> bool {
        self.0.load(Ordering::Acquire)
    }
}
#[derive(Clone)]
pub struct IngestOptions {
    pub max_commits: i64,
    pub only_path: Option<String>,
    /// Per repository subprocess budget, including pipe draining.
    pub timeout: Duration,
    pub cancellation: Cancellation,
    pub max_output_bytes: usize,
}
impl Default for IngestOptions {
    fn default() -> Self {
        Self {
            max_commits: 20_000,
            only_path: None,
            timeout: Duration::from_secs(30),
            cancellation: Cancellation::default(),
            max_output_bytes: 64 * 1024 * 1024,
        }
    }
}
#[derive(Clone)]
pub struct CochangeOptions {
    pub now_seconds: f64,
    pub min_confidence: f64,
    pub min_support: i64,
    pub min_llr: f64,
    pub limit: i64,
    pub auto_ingest: bool,
    pub ingest: IngestOptions,
}
impl Default for CochangeOptions {
    fn default() -> Self {
        Self {
            now_seconds: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs_f64(),
            min_confidence: 0.4,
            min_support: 3,
            min_llr: 3.841,
            limit: 15,
            auto_ingest: true,
            ingest: IngestOptions::default(),
        }
    }
}

pub fn ingest_commits(conn: &Connection, root: &Path, options: &IngestOptions) -> Result<Value> {
    let paths = crate::project(root)?;
    let repos = git::repositories(&paths, options);
    let mut total = 0;
    let mut per_repo = BTreeMap::new();
    let mut last_sha = None;
    let mut gaps = Vec::new();
    for rel in repos {
        if options.cancellation.is_cancelled() {
            gaps.push(json!({"repo":if rel.is_empty(){"."}else{&rel},"reason":"cancelled"}));
            break;
        }
        let key = if rel.is_empty() {
            "cochange_last_sha".into()
        } else {
            format!("cochange_last_sha:{rel}")
        };
        let previous: Option<String> = conn
            .query_row("SELECT value FROM meta WHERE key=?", [&key], |r| r.get(0))
            .optional()?;
        let range = previous
            .filter(|s| !s.is_empty())
            .map_or_else(|| "HEAD".to_owned(), |sha| format!("{sha}..HEAD"));
        let repo = paths.root().join(&rel);
        let commits = match git::log(&repo, &range, options) {
            Ok(commits) => commits,
            Err(reason) => {
                gaps.push(json!({"repo":if rel.is_empty(){"."}else{&rel},"reason":reason}));
                continue;
            }
        };
        if commits.is_empty() {
            continue;
        }
        // Each repository publishes commits, files and its last SHA atomically.
        // Dropping the transaction on any insertion failure rolls back all three.
        let transaction = conn.unchecked_transaction()?;
        let mut inserted = 0;
        for commit in commits.iter().rev() {
            let sha = if rel.is_empty() {
                commit.sha.clone()
            } else {
                format!("{rel}\u{1}{}", commit.sha)
            };
            let count = transaction.execute("INSERT OR IGNORE INTO cr_commits(sha,committed_at,author,subject,n_files) VALUES(?,?,?,?,?)", params![sha,commit.ts,commit.author,commit.subject,commit.files.len() as i64])?;
            if count == 0 {
                continue;
            }
            let id = transaction.last_insert_rowid();
            for file in &commit.files {
                let path = if rel.is_empty() {
                    file.clone()
                } else {
                    format!("{rel}/{file}")
                };
                transaction.execute(
                    "INSERT INTO cr_commit_files(commit_id,path) VALUES(?,?)",
                    params![id, path],
                )?;
            }
            inserted += 1;
        }
        transaction.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", params![key,commits[0].sha])?;
        transaction.commit()?;
        if rel.is_empty() {
            last_sha = Some(commits[0].sha.clone());
        }
        total += inserted;
        per_repo.insert(if rel.is_empty() { ".".into() } else { rel }, inserted);
    }
    let mut output = json!({"ok":true,"ingested":total,"repos":per_repo.len(),"per_repo":per_repo,"last_sha":last_sha});
    if !gaps.is_empty() {
        output["history_gaps"] = json!(gaps);
    }
    Ok(output)
}

struct CommitBasket {
    repo: String,
    files: BTreeSet<String>,
    weight: f64,
}
#[derive(Default)]
struct Support {
    weight: f64,
    count: i64,
    co_weight: f64,
    co_count: i64,
}

pub fn cochange(
    conn: &Connection,
    path: &str,
    root: Option<&Path>,
    options: &CochangeOptions,
) -> Result<Value> {
    let target = normalize(path);
    if options.auto_ingest
        && let Some(root) = root
    {
        let mut ingest = options.ingest.clone();
        ingest.only_path = Some(target.clone());
        let _ = ingest_commits(conn, root, &ingest);
    }
    let mut statement = conn.prepare("SELECT c.id,c.sha,c.committed_at,f.path FROM cr_commits c JOIN cr_commit_files f ON f.commit_id=c.id WHERE c.n_files<=30 ORDER BY c.id")?;
    let rows = statement.query_map([], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, Option<String>>(1)?,
            r.get::<_, f64>(2)?,
            r.get::<_, String>(3)?,
        ))
    })?;
    let mut baskets = BTreeMap::new();
    for row in rows {
        let (id, sha, timestamp, file) = row?;
        let basket = baskets.entry(id).or_insert_with(|| CommitBasket {
            repo: sha
                .as_deref()
                .and_then(|s| s.split_once('\u{1}'))
                .map_or("", |(repo, _)| repo)
                .to_owned(),
            weight: 0.5f64.powf(((options.now_seconds - timestamp) / 86400.0).max(0.0) / 90.0),
            files: BTreeSet::new(),
        });
        basket.files.insert(file);
    }
    if baskets.is_empty() {
        return Ok(
            json!({"ok":true,"path":target,"total_commits":0,"partners":[],"note":"no commit history ingested"}),
        );
    }
    let Some(repo) = baskets
        .values()
        .find(|b| b.files.contains(&target))
        .map(|b| b.repo.clone())
    else {
        return Ok(
            json!({"ok":true,"path":target,"total_commits":baskets.len(),"partners":[],"note":"target file has no co-change history"}),
        );
    };
    let scoped: Vec<_> = baskets.values().filter(|b| b.repo == repo).collect();
    let mut support: BTreeMap<String, Support> = BTreeMap::new();
    let mut total_weight = 0.0;
    for basket in &scoped {
        total_weight += basket.weight;
        let has_target = basket.files.contains(&target);
        for file in &basket.files {
            let s = support.entry(file.clone()).or_default();
            s.weight += basket.weight;
            s.count += 1;
            if has_target && file != &target {
                s.co_weight += basket.weight;
                s.co_count += 1;
            }
        }
    }
    let target_support = &support[&target];
    let neighbors = import_neighbors(conn, &target)?;
    let mut partners = Vec::new();
    for (path, stats) in &support {
        if stats.co_count == 0 || stats.co_count < options.min_support {
            continue;
        }
        let confidence = if target_support.weight != 0.0 {
            stats.co_weight / target_support.weight
        } else {
            0.0
        };
        if confidence < options.min_confidence {
            continue;
        }
        let p_file = if total_weight != 0.0 {
            stats.weight / total_weight
        } else {
            0.0
        };
        let p_joint = if total_weight != 0.0 {
            stats.co_weight / total_weight
        } else {
            0.0
        };
        let p_target = if total_weight != 0.0 {
            target_support.weight / total_weight
        } else {
            0.0
        };
        let lift = if p_file != 0.0 && p_target != 0.0 {
            p_joint / (p_target * p_file)
        } else {
            0.0
        };
        if lift <= 1.0 {
            continue;
        }
        let g2 = llr(
            stats.co_count,
            target_support.count,
            stats.count,
            scoped.len() as i64,
        );
        if g2 < options.min_llr {
            continue;
        }
        let raw_confidence = stats.co_count as f64 / target_support.count as f64;
        let lower = wilson_lower(stats.co_count, target_support.count);
        let strength = confidence * (lower / raw_confidence);
        let edge = neighbors.contains(path);
        partners.push(json!({"path":path,"support":stats.co_count,"confidence":rounded(confidence,3),"confidence_low":rounded(lower,3),"lift":rounded(lift,2),"llr":rounded(g2,1),"strength":rounded(strength,3),"has_import_edge":edge,"hidden_coupling":!edge}));
    }
    partners.sort_by(|a, b| {
        a["has_import_edge"]
            .as_bool()
            .cmp(&b["has_import_edge"].as_bool())
            .then_with(|| {
                b["strength"]
                    .as_f64()
                    .partial_cmp(&a["strength"].as_f64())
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| a["path"].as_str().cmp(&b["path"].as_str()))
    });
    partners.truncate(positive_limit(options.limit));
    Ok(
        json!({"ok":true,"path":target,"total_commits":scoped.len(),"target_commits":target_support.count,"scope":if repo.is_empty(){"."}else{&repo},"partners":partners}),
    )
}

fn import_neighbors(conn: &Connection, path: &str) -> Result<BTreeSet<String>> {
    let id: Option<i64> = conn
        .query_row("SELECT id FROM ci_files WHERE path=?", [path], |r| r.get(0))
        .optional()?;
    let Some(id) = id else {
        return Ok(BTreeSet::new());
    };
    let mut query = conn.prepare("SELECT dst.path FROM ci_imports i JOIN ci_files dst ON dst.id=i.to_file_id WHERE i.from_file_id=? UNION SELECT src.path FROM ci_imports i JOIN ci_files src ON src.id=i.from_file_id WHERE i.to_file_id=?")?;
    Ok(query
        .query_map([id, id], |r| r.get::<_, String>(0))?
        .collect::<rusqlite::Result<BTreeSet<_>>>()?)
}

pub fn llr(n_ab: i64, n_a: i64, n_b: i64, n: i64) -> f64 {
    let cells = [n_ab, n_a - n_ab, n_b - n_ab, n - n_a - n_b + n_ab];
    if n <= 0 || cells.iter().any(|v| *v < 0) {
        return 0.0;
    }
    let (a, b, n) = (n_a as f64, n_b as f64, n as f64);
    let expected = [
        a * b / n,
        a * (n - b) / n,
        (n - a) * b / n,
        (n - a) * (n - b) / n,
    ];
    (2.0 * cells
        .iter()
        .zip(expected)
        .filter(|(o, e)| **o > 0 && *e > 0.0)
        .map(|(o, e)| *o as f64 * (*o as f64 / e).ln())
        .sum::<f64>())
    .max(0.0)
}
pub fn wilson_lower(successes: i64, trials: i64) -> f64 {
    if trials <= 0 {
        return 0.0;
    }
    let (successes, trials, z) = (successes as f64, trials as f64, 1.96);
    let p = successes / trials;
    let z2 = z * z;
    let center = p + z2 / (2.0 * trials);
    let margin = z * (p * (1.0 - p) / trials + z2 / (4.0 * trials * trials)).sqrt();
    ((center - margin) / (1.0 + z2 / trials)).max(0.0)
}
