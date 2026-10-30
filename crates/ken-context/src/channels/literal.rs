use crate::{RankedItem, Result, text};
use ken_retrieval::vocabulary::is_name_stopword;
use ken_text::PythonText;
use rusqlite::Connection;
use std::{collections::BTreeSet, path::Path};
fn tokens(prompt: &str) -> BTreeSet<String> {
    let pattern = regex::Regex::new(r"[A-Za-z][A-Za-z0-9_.-]{2,}").expect("literal token syntax");
    let raw = pattern
        .find_iter(prompt)
        .map(|m| {
            m.as_str()
                .trim_matches(['`', '\'', '"', '(', ')', '[', ']', '{', '}'])
                .to_lowercase()
        })
        .collect::<Vec<_>>();
    let mut out = raw
        .iter()
        .filter(|s| s.len() >= 4 && !is_name_stopword(s) && s.contains(['_', '.', '-']))
        .cloned()
        .collect::<BTreeSet<_>>();
    let meaningful = raw
        .iter()
        .filter(|s| s.len() >= 3 && !is_name_stopword(s))
        .collect::<Vec<_>>();
    for pair in meaningful.windows(2) {
        let (left, right) = (pair[0], pair[1]);
        if [
            "case", "context", "expected", "file", "max", "min", "num", "rank", "top",
        ]
        .contains(&left.as_str())
            || [
                "chars", "count", "findings", "files", "id", "limit", "line", "path", "rank",
                "recall", "size", "symbols", "tokens",
            ]
            .contains(&right.as_str())
        {
            out.insert(format!("{left}_{right}"));
            out.insert(format!("{left}-{right}"));
        }
    }
    out
}
pub fn literal_content_scores(
    conn: &Connection,
    prompt: &PythonText,
    root: Option<&Path>,
) -> Result<Vec<RankedItem>> {
    let Some(root) = root else {
        return Ok(Vec::new());
    };
    let tokens = tokens(&text::matching(prompt));
    if tokens.is_empty() {
        return Ok(Vec::new());
    }
    let mut out = Vec::new();
    let mut stmt = conn.prepare("SELECT path FROM ci_files")?;
    for path in stmt.query_map([], |r| r.get::<_, String>(0))? {
        let path = path?;
        if path.starts_with("examples/bench/") {
            continue;
        }
        let absolute = root.join(&path);
        let Ok(metadata) = absolute.metadata() else {
            continue;
        };
        if !metadata.is_file() || metadata.len() > 256 * 1024 {
            continue;
        }
        let Ok(bytes) = std::fs::read(&absolute) else {
            continue;
        };
        let content = text::utf8_ignore(&bytes).to_lowercase();
        let overlap = tokens
            .iter()
            .filter(|token| content.contains(token.as_str()))
            .collect::<Vec<_>>();
        if overlap.is_empty() {
            continue;
        }
        let score = (1.15 + 0.45 * overlap.len() as f64).min(2.5);
        out.push(RankedItem::file(
            path,
            score,
            format!(
                "literal:{}",
                overlap
                    .into_iter()
                    .take(3)
                    .cloned()
                    .collect::<Vec<_>>()
                    .join(",")
            ),
        ));
    }
    Ok(out)
}
