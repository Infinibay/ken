//! Stable MinHash candidate retrieval, followed by exact shingle-set scores.
//! The captured permutation family is immutable algorithm definition data;
//! there is no Python RNG or numerical runtime dependency.
use crate::{HistoryError, Result, normalize, positive_limit, rounded};
use blake2::{
    Blake2bVar,
    digest::{Update, VariableOutput},
};
use ken_core::source_reader::SourceFileReader;
use rusqlite::Connection;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
    sync::OnceLock,
};
mod pair_order;

const PRIME: u64 = 2_147_483_647;
const NUM_PERM: usize = 64;
const MIN_SHINGLES: usize = 15;
const MAX_BUCKET: usize = 100;
#[derive(Clone)]
pub struct CloneOptions {
    pub min_similarity: f64,
    pub limit: i64,
    /// Live source is bounded through the existing confined source reader.
    /// A skipped read is exposed in `source_gaps`, rather than called absent.
    pub max_source_bytes: u64,
}
impl Default for CloneOptions {
    fn default() -> Self {
        Self {
            min_similarity: 0.75,
            limit: 10,
            max_source_bytes: 16 * 1024 * 1024,
        }
    }
}

fn token_hash(token: &str) -> u64 {
    let mut hash = Blake2bVar::new(8).expect("fixed legal Blake2b digest size");
    hash.update(token.as_bytes());
    let mut digest = [0u8; 8];
    hash.finalize_variable(&mut digest)
        .expect("fixed digest size");
    u64::from_be_bytes(digest) % PRIME
}
pub fn shingles(source: &str) -> BTreeSet<u64> {
    static COMMENT: OnceLock<regex::Regex> = OnceLock::new();
    static TOKEN: OnceLock<regex::Regex> = OnceLock::new();
    let comment =
        COMMENT.get_or_init(|| regex::Regex::new(r"(?m)#.*$|//.*$").expect("constant regex"));
    let token = TOKEN.get_or_init(|| regex::Regex::new(r"[A-Za-z0-9_]+").expect("constant regex"));
    let text = comment.replace_all(source, "").to_lowercase();
    let mut cache = BTreeMap::new();
    let tokens: Vec<u64> = token
        .find_iter(&text)
        .map(|t| {
            *cache
                .entry(t.as_str())
                .or_insert_with(|| token_hash(t.as_str()))
        })
        .collect();
    tokens
        .windows(5)
        .map(|window| {
            window
                .iter()
                .fold(0, |acc, t| (acc * 1_000_003 + t) % PRIME)
        })
        .collect()
}
#[derive(Deserialize)]
struct Permutations {
    prime: u64,
    a: Vec<u64>,
    b: Vec<u64>,
}
fn permutations() -> &'static Permutations {
    static DATA: OnceLock<Permutations> = OnceLock::new();
    DATA.get_or_init(|| {
        let data: Permutations =
            serde_json::from_str(include_str!("../resources/minhash-permutations.json"))
                .expect("immutable permutation data");
        assert_eq!(data.prime, PRIME);
        assert_eq!(data.a.len(), NUM_PERM);
        assert_eq!(data.b.len(), NUM_PERM);
        assert!(data.a.iter().all(|a| *a > 0 && *a < PRIME));
        assert!(data.b.iter().all(|b| *b < PRIME));
        data
    })
}
pub fn signature(shingles: &BTreeSet<u64>) -> Result<Vec<u64>> {
    if shingles.is_empty() {
        return Err(HistoryError::Invalid(
            "a MinHash signature requires at least one shingle".into(),
        ));
    }
    if shingles.iter().any(|s| *s >= PRIME) {
        return Err(HistoryError::Invalid(
            "shingle is outside the 31-bit permutation field".into(),
        ));
    }
    let p = permutations();
    Ok(p.a
        .iter()
        .zip(&p.b)
        .map(|(a, b)| {
            shingles
                .iter()
                .map(|s| (a * s + b) % PRIME)
                .min()
                .expect("nonempty shingles")
        })
        .collect())
}
pub fn lsh_params(threshold: f64) -> (usize, usize) {
    // Python min/max choose the finite first argument when threshold is NaN.
    let s = if threshold.is_nan() {
        0.01
    } else {
        threshold.clamp(0.01, 0.999)
    };
    let mut best: Option<(f64, usize, usize)> = None;
    let mut fallback: Option<(f64, usize, usize)> = None;
    for rows in 1..=NUM_PERM {
        let bands = NUM_PERM / rows;
        let recall = 1.0 - (1.0 - s.powf(rows as f64)).powf(bands as f64);
        let false_positive = 1.0 - (1.0 - (0.5 * s).powf(rows as f64)).powf(bands as f64);
        if fallback.is_none_or(|(old, _, _)| recall > old) {
            fallback = Some((recall, bands, rows));
        }
        if recall >= 0.98 && best.is_none_or(|(old, _, _)| false_positive < old) {
            best = Some((false_positive, bands, rows));
        }
    }
    let (_, bands, rows) = best.or(fallback).expect("at least one banding");
    (bands, rows)
}
pub fn exact_similarity(a: &BTreeSet<u64>, b: &BTreeSet<u64>) -> (f64, f64) {
    if a.is_empty() || b.is_empty() {
        return (0.0, 0.0);
    }
    let intersection = a.intersection(b).count();
    if intersection == 0 {
        return (0.0, 0.0);
    }
    (
        intersection as f64 / (a.len() + b.len() - intersection) as f64,
        intersection as f64 / a.len().min(b.len()) as f64,
    )
}
struct Symbol {
    id: i64,
    qualname: String,
    file: String,
    line: i64,
    end: i64,
    shingles: BTreeSet<u64>,
    signature: Vec<u64>,
}
impl Symbol {
    fn size(&self) -> i64 {
        self.end - self.line + 1
    }
    fn summary(&self) -> Value {
        json!({"qualname":self.qualname,"file":self.file,"line":self.line})
    }
    fn detail(&self) -> Value {
        json!({"qualname":self.qualname,"file":self.file,"line":self.line,"line_end":self.end,"size":self.size()})
    }
}

pub fn clones(
    conn: &Connection,
    path: Option<&str>,
    qualname: Option<&str>,
    root: Option<&Path>,
    options: &CloneOptions,
) -> Result<Value> {
    let Some(root) = root else {
        return Ok(json!({"ok":false,"error":"project_root required"}));
    };
    let paths = crate::project(root)?;
    let reader = SourceFileReader::new(&paths)?;
    let mut statement=conn.prepare("SELECT s.id,s.qualname,s.name,s.kind,s.line_start,s.line_end,f.path FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id WHERE s.kind IN ('function','method','class')")?;
    let rows = statement.query_map([], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, Option<String>>(1)?,
            r.get::<_, String>(2)?,
            r.get::<_, i64>(4)?,
            r.get::<_, i64>(5)?,
            r.get::<_, String>(6)?,
        ))
    })?;
    let mut symbols = Vec::new();
    let mut gaps = BTreeMap::new();
    for row in rows {
        let (id, qualname, name, line, end, file) = row?;
        let bytes = match reader
            .open(Path::new(&file))
            .and_then(|f| f.read_bounded(options.max_source_bytes))
        {
            Ok(Some(bytes)) => bytes,
            Ok(None) => {
                gaps.insert(file, json!("source byte limit exceeded"));
                continue;
            }
            Err(e) => {
                gaps.insert(file, json!(e.to_string()));
                continue;
            }
        };
        let text = String::from_utf8_lossy(&bytes);
        let lines = crate::source_lines(&text);
        let start = usize::try_from(line.saturating_sub(1).max(0))
            .unwrap_or(usize::MAX)
            .min(lines.len());
        let stop = usize::try_from(line.saturating_sub(1).max(end).max(0))
            .unwrap_or(usize::MAX)
            .min(lines.len());
        let source = lines[start..stop.max(start)].join("\n");
        let shingles = shingles(&source);
        if shingles.len() < MIN_SHINGLES {
            continue;
        }
        let signature = signature(&shingles)?;
        symbols.push(Symbol {
            id,
            qualname: qualname.filter(|s| !s.is_empty()).unwrap_or(name),
            file,
            line,
            end,
            shingles,
            signature,
        });
    }
    if symbols.is_empty() {
        let mut out = json!({"ok":true,"clones":[],"note":"no symbols large enough to compare"});
        if !gaps.is_empty() {
            out["source_gaps"] = json!(gaps);
        }
        return Ok(out);
    }
    let (bands, rows) = lsh_params(options.min_similarity);
    // Both bucket encounter order and the subsequent pair-table order are
    // observable when all public score/file sort keys tie at the result limit.
    let mut bucket_positions: BTreeMap<(usize, Vec<u64>), usize> = BTreeMap::new();
    let mut buckets: Vec<Vec<usize>> = Vec::new();
    for (index, symbol) in symbols.iter().enumerate() {
        for band in 0..bands {
            let position = *bucket_positions
                .entry((
                    band,
                    symbol.signature[band * rows..(band + 1) * rows].to_vec(),
                ))
                .or_insert_with(|| {
                    buckets.push(Vec::new());
                    buckets.len() - 1
                });
            buckets[position].push(index);
        }
    }
    let mut candidates = pair_order::PairOrder::new();
    let mut skipped = 0;
    for members in &buckets {
        if members.len() > MAX_BUCKET {
            skipped += 1;
            continue;
        }
        for (pos, &a) in members.iter().enumerate() {
            for &b in &members[pos + 1..] {
                let (a, b) = if symbols[a].id < symbols[b].id {
                    (a, b)
                } else {
                    (b, a)
                };
                candidates.insert(symbols[a].id, symbols[b].id);
            }
        }
    }
    let by_id: BTreeMap<_, _> = symbols
        .iter()
        .enumerate()
        .map(|(index, s)| (s.id, index))
        .collect();
    let candidates: Vec<_> = candidates
        .pairs()
        .map(|(a, b)| (by_id[&a], by_id[&b]))
        .collect();
    let note=(skipped>0).then(||format!("{skipped} LSH bucket(s) held more than {MAX_BUCKET} near-identical symbols (boilerplate) and were not expanded"));
    let mut out;
    if let Some(path) = path {
        let target = normalize(path);
        let target_ids: BTreeSet<_> = symbols
            .iter()
            .filter(|s| {
                s.file == target
                    && qualname
                        .is_none_or(|q| s.qualname == q || s.qualname.ends_with(&format!(".{q}")))
            })
            .map(|s| s.id)
            .collect();
        if target_ids.is_empty() {
            return Ok(
                json!({"ok":false,"error":"symbol not found / too small to compare","path":target,"qualname":qualname}),
            );
        }
        let mut matches = Vec::new();
        for (a, b) in candidates {
            let other = if target_ids.contains(&symbols[a].id) {
                b
            } else if target_ids.contains(&symbols[b].id) {
                a
            } else {
                continue;
            };
            let (sim, contain) = exact_similarity(&symbols[a].shingles, &symbols[b].shingles);
            if sim >= options.min_similarity {
                matches.push((
                    sim,
                    contain,
                    other,
                    symbols[a].size().min(symbols[b].size()),
                ));
            }
        }
        matches.sort_by(|a, b| {
            (-a.0 * a.3 as f64)
                .total_cmp(&(-b.0 * b.3 as f64))
                .then_with(|| symbols[a.2].file.cmp(&symbols[b.2].file))
        });
        let results: Vec<_> = matches
            .iter()
            .take(positive_limit(options.limit))
            .map(|&(sim, contain, other, _)| {
                let mut meta = symbols[other].detail();
                meta["similarity"] = json!(rounded(sim, 3));
                meta["containment"] = json!(rounded(contain, 3));
                meta
            })
            .collect();
        out = json!({"ok":true,"path":target,"qualname":qualname,"clones":results});
    } else {
        let mut matches = Vec::new();
        for (a, b) in candidates {
            let (sim, contain) = exact_similarity(&symbols[a].shingles, &symbols[b].shingles);
            if sim >= options.min_similarity {
                matches.push((sim, contain, a, b));
            }
        }
        matches.sort_by(|a, b| {
            (-a.0 * symbols[a.2].size().min(symbols[a.3].size()) as f64)
                .total_cmp(&(-b.0 * symbols[b.2].size().min(symbols[b.3].size()) as f64))
                .then_with(|| symbols[a.2].file.cmp(&symbols[b.2].file))
                .then_with(|| symbols[a.3].file.cmp(&symbols[b.3].file))
        });
        let results:Vec<_>=matches.iter().take(positive_limit(options.limit)).map(|&(sim,contain,a,b)|json!({"similarity":rounded(sim,3),"containment":rounded(contain,3),"a":symbols[a].summary(),"b":symbols[b].summary()})).collect();
        out = json!({"ok":true,"clones":results});
    }
    if let Some(note) = note {
        out["note"] = json!(note);
    }
    if !gaps.is_empty() {
        out["source_gaps"] = json!(gaps);
    }
    Ok(out)
}
