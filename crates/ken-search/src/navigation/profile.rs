//! Extractive responsibility briefs from indexed vocabulary and its contrast corpus.
use super::{IndexNavigation, Result};
use ken_core::tool_output::Document;
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
};

const STOP: &[&str] = &[
    "the", "and", "for", "with", "from", "this", "that", "self", "return", "none", "true", "false",
    "init", "str", "int", "list", "dict", "test", "get", "set", "py", "ts", "js",
];
type Counts = BTreeMap<String, usize>;

fn tokens(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    for chunk in text.split(|c: char| !c.is_ascii_alphanumeric()) {
        let mut start = 0;
        let bytes = chunk.as_bytes();
        for end in 1..=bytes.len() {
            if end == bytes.len()
                || ((bytes[end - 1].is_ascii_lowercase() || bytes[end - 1].is_ascii_digit())
                    && bytes[end].is_ascii_uppercase())
            {
                let term = chunk[start..end].to_ascii_lowercase();
                if term.len() >= 3
                    && !STOP.contains(&term.as_str())
                    && !term.bytes().all(|c| c.is_ascii_digit())
                {
                    out.push(term);
                }
                start = end;
            }
        }
    }
    out
}
fn count(counts: &mut Counts, text: &str) {
    for token in tokens(text) {
        *counts.entry(token).or_default() += 1;
    }
}

impl IndexNavigation {
    /// Distinguishing terms for a file or directory. Exact-score ties use lexical
    /// order; the original's Python set iteration has no stable ordering there.
    pub fn profile(&self, path: &str, granularity: &str, top_terms: i64) -> Result<Document> {
        // Preserve Path.as_posix().lstrip("./"), including its hidden-name and
        // root-directory behavior; these are index labels, not source opens.
        let normalized = Path::new(path)
            .components()
            .map(|c| c.as_os_str().to_string_lossy())
            .collect::<Vec<_>>()
            .join("/");
        let target = normalized.trim_start_matches(['.', '/']);
        let files = self
            .conn
            .prepare("SELECT id,path FROM ci_files")?
            .query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        let is_dir = granularity == "dir";
        let prefix = format!("{}/", target.trim_end_matches('/'));
        let selected = files
            .iter()
            .filter(|(_, path)| path == target || (is_dir && path.starts_with(&prefix)))
            .map(|(id, _)| *id)
            .collect::<BTreeSet<_>>();
        if selected.is_empty() {
            return Ok(
                doc!("ok": false, "error": if is_dir { "no indexed files under path" } else { "file not indexed" }, "path": target),
            );
        }
        let label = if is_dir {
            target.trim_end_matches('/')
        } else {
            target
        };
        let label = if label.is_empty() { "(root)" } else { label };
        let mut target_counts = Counts::new();
        let mut rest_counts = Counts::new();
        let mut symbols = self.conn.prepare("SELECT s.file_id,s.name,s.qualname,s.docstring FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id")?;
        let mut rows = symbols.query([])?;
        while let Some(row) = rows.next()? {
            let counts = if selected.contains(&row.get::<_, i64>(0)?) {
                &mut target_counts
            } else {
                &mut rest_counts
            };
            for column in 1..=3 {
                count(
                    counts,
                    &row.get::<_, Option<String>>(column)?.unwrap_or_default(),
                );
            }
        }
        let mut intent = self.conn.prepare(
            "SELECT s.file_id,s.text FROM ci_intent_sources s JOIN ci_files f ON f.id=s.file_id",
        )?;
        let mut rows = intent.query([])?;
        while let Some(row) = rows.next()? {
            let counts = if selected.contains(&row.get::<_, i64>(0)?) {
                &mut target_counts
            } else {
                &mut rest_counts
            };
            count(counts, &row.get::<_, String>(1)?);
        }
        let n_t = target_counts.values().sum::<usize>();
        let n_r = rest_counts.values().sum::<usize>();
        if n_t == 0 {
            return Ok(
                doc!("ok": true, "label": label, "granularity": granularity, "distinguishing_terms": Vec::<Document>::new(), "evidence_strength": "none", "note": "no indexable terms (no symbols/docstrings)"),
            );
        }
        let mut scored = Vec::new();
        for (term, &y_t) in &target_counts {
            let y_r = rest_counts.get(term).copied().unwrap_or_default();
            let prior = 1000.0 * ((y_t + y_r) as f64 / (n_t + n_r) as f64);
            let num_t = y_t as f64 + prior;
            let den_t = n_t as f64 + 1000.0 - y_t as f64 - prior;
            let num_r = y_r as f64 + prior;
            let den_r = n_r as f64 + 1000.0 - y_r as f64 - prior;
            if den_t <= 0.0 || den_r <= 0.0 || num_t <= 0.0 || num_r <= 0.0 {
                continue;
            }
            let delta = (num_t / den_t).ln() - (num_r / den_r).ln();
            let variance = 1.0 / num_t + 1.0 / num_r;
            let z = delta / variance.sqrt();
            if z > 0.0 {
                scored.push((z, term, y_t));
            }
        }
        scored.sort_by(|a, b| b.0.total_cmp(&a.0).then_with(|| a.1.cmp(b.1)));
        let terms = scored
            .into_iter()
            .take(top_terms.max(1) as usize)
            .map(|(z, term, count)| {
                let z = format!("{z:.2}")
                    .parse::<f64>()
                    .expect("finite log-odds score");
                doc!("term": term.as_str(), "z": z, "count": count)
            })
            .collect::<Vec<_>>();
        Ok(
            doc!("ok": true, "label": label, "granularity": granularity, "files": selected.len(), "term_count": n_t, "evidence_strength": if n_t >= 200 { "strong" } else if n_t >= 40 { "moderate" } else { "thin" }, "distinguishing_terms": terms),
        )
    }
}
