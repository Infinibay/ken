use crate::{RankedItem, Result, text};
use ken_text::PythonText;
use rusqlite::{Connection, params};
use std::collections::BTreeSet;
fn regex(pattern: &str) -> regex::Regex {
    regex::Regex::new(pattern).expect("constant mention syntax")
}
fn known(path: &str) -> bool {
    path.rsplit('.').next().is_some_and(|ext| {
        [
            "py", "pyi", "rs", "js", "jsx", "mjs", "cjs", "ts", "tsx", "go", "java", "md", "rst",
            "json", "yaml", "yml", "toml", "sh", "sql", "html", "css",
        ]
        .contains(&ext.to_lowercase().as_str())
    })
}
fn path_regex() -> regex::Regex {
    regex(r"\b[\w./\-]+\.[a-zA-Z]{1,5}\b(?::\d+(?:-\d+)?)?")
}
/// Source-shaped tokens; consumers own their identity-resolution policy.
pub fn source_path_mentions(value: &PythonText) -> Vec<String> {
    let value = text::matching(value);
    path_regex()
        .find_iter(&value)
        .filter_map(|matched| {
            let base = matched.as_str().split(':').next().unwrap_or("");
            known(base).then(|| base.to_owned())
        })
        .collect()
}
fn at_line(
    conn: &Connection,
    path: &str,
    line: i64,
    seen: &mut BTreeSet<String>,
    symbols: &mut Vec<RankedItem>,
) -> Result<()> {
    let mut stmt=conn.prepare("SELECT s.qualname,s.line_start,f.path FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id WHERE f.path=? AND s.line_start<=? AND s.line_end>=? ORDER BY(s.line_end-s.line_start),s.line_start LIMIT 2")?;
    for row in stmt.query_map(params![path, line, line], |r| {
        Ok((
            r.get::<_, String>(0)?,
            r.get::<_, i64>(1)?,
            r.get::<_, String>(2)?,
        ))
    })? {
        let (qual, line, path) = row?;
        let target = format!("{qual} ({path}:{line})");
        if seen.insert(target.clone()) {
            symbols.push(RankedItem::symbol(target, 6., "explicit-line-mention"));
        }
    }
    Ok(())
}
pub fn explicit_mentions(
    conn: &Connection,
    prompt: &PythonText,
) -> Result<(Vec<RankedItem>, Vec<RankedItem>)> {
    let prompt = text::matching(prompt);
    let (mut files, mut symbols) = (Vec::new(), Vec::new());
    let (mut seen_files, mut seen_symbols) = (BTreeSet::new(), BTreeSet::new());
    let paths = path_regex();
    let mut lookup = conn.prepare("SELECT path FROM ci_files WHERE path=? OR path LIKE ?")?;
    for matched in paths.find_iter(&prompt) {
        let mut parts = matched.as_str().split(':');
        let base = parts.next().unwrap_or("");
        let line = parts
            .next()
            .and_then(|s| s.split('-').next())
            .and_then(|s| s.parse::<i64>().ok());
        if !known(base) || !seen_files.insert(base.to_owned()) {
            continue;
        }
        for path in lookup.query_map(params![base, format!("%/{base}")], |r| {
            r.get::<_, String>(0)
        })? {
            let path = path?;
            files.push(RankedItem::file(path.clone(), 5., "explicit-mention"));
            if let Some(line) = line {
                at_line(conn, &path, line, &mut seen_symbols, &mut symbols)?;
            }
        }
    }
    let trace =
        regex(r#"File "([^"\n]+)", line (\d+)|File\s+([\w./\-]+\.[a-zA-Z]{1,5})\s+line\s+(\d+)"#);
    for m in trace.captures_iter(&prompt) {
        let base = m.get(1).or_else(|| m.get(3)).unwrap().as_str();
        let line = m
            .get(2)
            .or_else(|| m.get(4))
            .unwrap()
            .as_str()
            .parse::<i64>();
        if !known(base) {
            continue;
        }
        let Ok(line) = line else {
            continue;
        };
        for path in lookup.query_map(params![base, format!("%/{base}")], |r| {
            r.get::<_, String>(0)
        })? {
            let path = path?;
            if seen_files.insert(path.clone()) {
                files.push(RankedItem::file(path.clone(), 5., "explicit-mention"));
            }
            at_line(conn, &path, line, &mut seen_symbols, &mut symbols)?;
        }
    }
    let mut candidates = BTreeSet::new();
    for capture in regex(r"`([^`\n]+)`|\b([A-Z][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\b")
        .captures_iter(&prompt)
    {
        let token = capture
            .get(1)
            .or_else(|| capture.get(2))
            .unwrap()
            .as_str()
            .trim()
            .trim_end_matches(['(', ')'])
            .trim();
        if (3..=80).contains(&token.chars().count()) {
            candidates.insert(token.to_owned());
        }
    }
    for token in regex(r"\b[A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]*\b").find_iter(&prompt) {
        let token = token.as_str().trim().trim_end_matches(['(', ')']).trim();
        if (3..=80).contains(&token.len()) {
            candidates.insert(token.to_owned());
        }
    }
    let mut statement=conn.prepare("SELECT s.qualname,s.name,f.path,s.line_start FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id WHERE s.qualname=? OR s.name=?")?;
    for token in candidates {
        if !seen_symbols.insert(token.clone()) {
            continue;
        }
        for row in statement.query_map(params![token, token], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(2)?,
                r.get::<_, i64>(3)?,
            ))
        })? {
            let (qual, path, line) = row?;
            symbols.push(RankedItem::symbol(
                format!("{qual} ({path}:{line})"),
                5.5,
                "explicit-mention",
            ));
            if !seen_files.contains(&path) {
                files.push(RankedItem::file(path, 3.5, "explicit-symbol-mention"));
            }
        }
    }
    Ok((files, symbols))
}
