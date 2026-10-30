//! Ordered post-merge evidence transformations. Channel scores stay immutable.
use crate::{
    Clock, Policy, RankedItem, Result,
    channels::{SimilarPrompt, base_rate_discount, file_base_rates},
    model::sort_items,
    text,
};
use rusqlite::{Connection, OptionalExtension, params_from_iter, types::Value};
use std::collections::{BTreeMap, BTreeSet};
fn add_reason(item: &mut RankedItem, reason: String) {
    item.reason = text::append(&item.reason, " + ", reason);
}
fn path(item: &RankedItem) -> Option<String> {
    item.target.to_utf8()
}
fn position(files: &[RankedItem], path: &str) -> Option<usize> {
    files
        .iter()
        .position(|item| item.target.to_utf8().as_deref() == Some(path))
}
fn placeholders(n: usize) -> String {
    vec!["?"; n].join(",")
}
pub(crate) fn symbol_path(target: &str) -> Option<&str> {
    let (_, location) = target.rsplit_once(" (")?;
    let (path, line) = location.rsplit_once(':')?;
    let line = line.strip_suffix(')')?;
    (!line.is_empty() && line.chars().all(ken_text::unicode::decimal)).then_some(path)
}
pub(crate) fn symbol_file_affinity(
    conn: &Connection,
    files: &mut Vec<RankedItem>,
    symbols: &[RankedItem],
) -> Result<()> {
    let mut sorted = symbols.to_vec();
    sort_items(&mut sorted);
    let mut best = Vec::<(String, f64, String)>::new();
    for symbol in sorted {
        if symbol.score < 1.5 {
            continue;
        }
        let Some(target) = symbol.target.to_utf8() else {
            continue;
        };
        let path = if let Some(path) = symbol_path(&target) {
            Some(path.to_owned())
        } else {
            conn.query_row("SELECT f.path FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id WHERE s.qualname=?1 OR s.name=?1 ORDER BY s.line_start LIMIT 1",[&target],|r|r.get::<_,String>(0)).optional()?
        };
        let Some(path) = path else { continue };
        #[expect(
            clippy::manual_clamp,
            reason = "Ordered max/min maps NaN to the established floor; clamp would preserve NaN."
        )]
        let contribution = (symbol.score * 0.35).max(0.7).min(2.);
        if let Some(old) = best.iter_mut().find(|row| row.0 == path) {
            if contribution > old.1 {
                *old = (path, contribution, target);
            }
        } else {
            best.push((path, contribution, target));
        }
    }
    best.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
    for (path, contribution, target) in best.into_iter().take(8) {
        if let Some(i) = position(files, &path) {
            files[i].score += contribution;
            add_reason(&mut files[i], format!("symbol-file+{contribution:.1}"));
        } else {
            files.push(RankedItem::file(
                path,
                contribution,
                format!("symbol-file({target})"),
            ));
        }
    }
    Ok(())
}
pub(crate) fn freshness(conn: &Connection, files: &mut [RankedItem], clock: &Clock) -> Result<()> {
    if files.is_empty() {
        return Ok(());
    }
    let paths = files.iter().filter_map(path).collect::<Vec<_>>();
    let mut mtimes = BTreeMap::new();
    for chunk in paths.chunks(500) {
        let mut stmt = conn.prepare(&format!(
            "SELECT path,mtime FROM ci_files WHERE path IN ({})",
            placeholders(chunk.len())
        ))?;
        for row in stmt.query_map(params_from_iter(chunk), |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?))
        })? {
            let (path, mtime) = row?;
            mtimes.insert(path, mtime);
        }
    }
    for item in files {
        let Some(mtime) = item.target.to_utf8().and_then(|p| mtimes.get(&p).copied()) else {
            continue;
        };
        let days = ((clock.now_ns as f64 - mtime as f64) / 1e9 / 86400.).max(0.);
        if days >= 7. {
            continue;
        }
        let mult = 1. + (1.3 - 1.) * (1. - days / 7.);
        item.score *= mult;
        add_reason(item, format!("fresh×{mult:.2}"));
    }
    Ok(())
}
pub(crate) fn cooc(
    conn: &Connection,
    files: &mut Vec<RankedItem>,
    clock: &Clock,
    policy: &Policy,
) -> Result<()> {
    let anchors = files
        .iter()
        .filter(|it| it.score >= 0.6)
        .take(5)
        .filter_map(|it| path(it).map(|p| (p, it.score)))
        .collect::<Vec<_>>();
    if anchors.is_empty() {
        return Ok(());
    }
    let paths = anchors.iter().map(|r| r.0.clone()).collect::<BTreeSet<_>>();
    let cutoff = (clock.now_ms / 1000 - 90 * 86400) * 1000;
    let mut values = paths
        .iter()
        .map(|s| Value::Text(s.clone()))
        .collect::<Vec<_>>();
    values.extend([Value::Real(0.6), Value::Integer(cutoff)]);
    let mut stmt=conn.prepare(&format!("SELECT DISTINCT session_id FROM cr_session_scores WHERE target_path IN ({}) AND score>=? AND created_at>=?",placeholders(paths.len())))?;
    let sessions = stmt
        .query_map(params_from_iter(values), |r| r.get::<_, i64>(0))?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    if sessions.is_empty() {
        return Ok(());
    }
    let mut values = sessions
        .iter()
        .map(|id| Value::Integer(*id))
        .collect::<Vec<_>>();
    values.extend(paths.iter().map(|p| Value::Text(p.clone())));
    let mut stmt=conn.prepare(&format!("SELECT target_path,COUNT(DISTINCT session_id) AS sess FROM cr_session_scores WHERE session_id IN ({}) AND target_path IS NOT NULL AND target_path NOT IN ({}) GROUP BY target_path HAVING sess>=2",placeholders(sessions.len()),placeholders(paths.len())))?;
    let (n, df) = if policy.lift {
        file_base_rates(conn)?
    } else {
        (0, BTreeMap::new())
    };
    let average = ken_retrieval::vector_math::python_sum_f64(
        &anchors.iter().map(|r| r.1).collect::<Vec<_>>(),
    ) / anchors.len() as f64;
    for row in stmt.query_map(params_from_iter(values), |r| {
        Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?))
    })? {
        let (path, count) = row?;
        let mut contribution = average * 0.4 * (count as f64 / 5.).min(1.);
        if policy.lift {
            contribution *= base_rate_discount(n, &df, &path);
        }
        if contribution < 0.3 {
            continue;
        }
        if let Some(i) = position(files, &path) {
            files[i].score += contribution;
            add_reason(&mut files[i], format!("cooc+{contribution:.1}"));
        } else {
            files.push(RankedItem::file(
                path,
                contribution,
                format!("cooc({count}sess)"),
            ));
        }
    }
    Ok(())
}
pub(crate) fn dismissal(
    conn: &Connection,
    files: &mut [RankedItem],
    similar: &[SimilarPrompt],
) -> Result<()> {
    if files.is_empty() || similar.is_empty() {
        return Ok(());
    }
    let sessions = similar
        .iter()
        .map(|s| s.session_id)
        .collect::<BTreeSet<_>>();
    let paths = files.iter().filter_map(path).collect::<Vec<_>>();
    if paths.is_empty() {
        return Ok(());
    }
    let mut values = paths
        .iter()
        .map(|s| Value::Text(s.clone()))
        .collect::<Vec<_>>();
    values.extend(sessions.iter().map(|s| Value::Integer(*s)));
    let mut stmt=conn.prepare(&format!("SELECT target_path,COUNT(DISTINCT session_id) FROM cr_interactions WHERE event_type='dismissed' AND target_kind='file' AND target_path IN ({}) AND session_id IN ({}) GROUP BY target_path",placeholders(paths.len()),placeholders(sessions.len())))?;
    for row in stmt.query_map(params_from_iter(values), |r| {
        Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?))
    })? {
        let (path, n) = row?;
        if let Some(i) = position(files, &path) {
            let damp = 1.5 * n.min(3) as f64 / 3.;
            files[i].score = (files[i].score - damp).max(0.);
            add_reason(&mut files[i], format!("-dismiss({damp:.1})"));
        }
    }
    Ok(())
}
pub(crate) fn is_test(path: &str) -> bool {
    let lower = path.to_lowercase();
    let name = lower.rsplit('/').next().unwrap_or("");
    lower.contains("/test/")
        || lower.contains("/tests/")
        || lower.starts_with("test/")
        || lower.starts_with("tests/")
        || name.starts_with("test_")
        || name.ends_with("_test.py")
        || name.contains(".test.")
        || name.contains(".spec.")
}
pub(crate) struct PathIndex {
    names: BTreeMap<String, Vec<String>>,
    tests: Vec<(String, String)>,
}
impl PathIndex {
    pub(crate) fn new(paths: &[String]) -> Self {
        let mut out = Self {
            names: BTreeMap::new(),
            tests: Vec::new(),
        };
        for path in paths {
            let name = path.rsplit('/').next().unwrap_or("").to_owned();
            out.names
                .entry(name.clone())
                .or_default()
                .push(path.clone());
            if is_test(path) {
                out.tests.push((name.to_lowercase(), path.clone()));
            }
        }
        out
    }
    pub(crate) fn related(&self, path: &str) -> Vec<String> {
        if is_test(path) {
            self.sources(path)
        } else {
            self.tests(path)
        }
    }
    fn sources(&self, path: &str) -> Vec<String> {
        let name = path.rsplit('/').next().unwrap_or("");
        let mut stem = name.rsplit_once('.').map_or(name, |r| r.0);
        for suffix in [".test", ".spec", "_test"] {
            if let Some(value) = stem.strip_suffix(suffix) {
                stem = value;
                break;
            }
        }
        stem = stem.strip_prefix("test_").unwrap_or(stem);
        if stem.is_empty() {
            return Vec::new();
        }
        let mut out = BTreeSet::new();
        for extension in ["py", "pyi", "ts", "tsx", "js", "jsx", "go", "rs", "java"] {
            for path in self
                .names
                .get(&format!("{stem}.{extension}"))
                .into_iter()
                .flatten()
            {
                if !is_test(path) {
                    out.insert(path.clone());
                }
            }
        }
        out.into_iter().collect()
    }
    fn tests(&self, path: &str) -> Vec<String> {
        let name = path.rsplit('/').next().unwrap_or("");
        let stem = name.rsplit_once('.').map_or(name, |r| r.0);
        if stem.is_empty() || stem.starts_with("test_") {
            return Vec::new();
        }
        let mut out = BTreeSet::new();
        for name in [
            format!("test_{stem}.py"),
            format!("{stem}_test.py"),
            format!("{stem}.test.py"),
            format!("test_{stem}.ts"),
            format!("{stem}.test.ts"),
            format!("{stem}.spec.ts"),
            format!("test_{stem}.js"),
            format!("{stem}.test.js"),
            format!("{stem}.spec.js"),
        ] {
            out.extend(self.names.get(&name).into_iter().flatten().cloned());
        }
        let needle = stem.to_lowercase();
        for (name, path) in &self.tests {
            if name.contains(&needle) {
                out.insert(path.clone());
            }
        }
        out.into_iter().collect()
    }
}
pub(crate) fn all_paths(conn: &Connection) -> Result<Vec<String>> {
    let mut stmt = conn.prepare("SELECT path FROM ci_files")?;
    Ok(stmt
        .query_map([], |r| r.get(0))?
        .collect::<rusqlite::Result<_>>()?)
}
pub(crate) fn test_affinity(conn: &Connection, files: &mut Vec<RankedItem>) -> Result<()> {
    let mut order = files
        .iter()
        .enumerate()
        .filter(|(_, it)| it.score >= 1.)
        .map(|(i, it)| (i, it.clone()))
        .collect::<Vec<_>>();
    order.sort_by(|a, b| {
        b.1.score
            .partial_cmp(&a.1.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.1.target.codepoints().cmp(b.1.target.codepoints()))
    });
    order.truncate(5);
    let index = PathIndex::new(&all_paths(conn)?);
    for (i, _) in order {
        let Some(anchor) = path(&files[i]) else {
            continue;
        };
        let minimum = if is_test(&anchor) { 1. } else { 0.5 };
        let contribution = (files[i].score * 0.35).max(minimum);
        for path in index.related(&anchor) {
            if let Some(i) = position(files, &path) {
                files[i].score += contribution;
                add_reason(&mut files[i], format!("test-affinity+{contribution:.1}"));
            } else {
                files.push(RankedItem::file(
                    path,
                    contribution,
                    format!("test-affinity({anchor})"),
                ));
            }
        }
    }
    Ok(())
}
pub(crate) fn import_affinity(conn: &Connection, files: &mut Vec<RankedItem>) -> Result<()> {
    let anchors = files
        .iter()
        .filter(|it| it.score >= 1.2)
        .take(5)
        .filter_map(|it| path(it).map(|p| (p, it.score)))
        .collect::<BTreeMap<_, _>>();
    if anchors.is_empty() {
        return Ok(());
    }
    let mut stmt=conn.prepare("SELECT src.path,dst.path FROM ci_imports i JOIN ci_files src ON src.id=i.from_file_id JOIN ci_files dst ON dst.id=i.to_file_id")?;
    let edges = stmt
        .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    let mut degree = BTreeMap::<String, i64>::new();
    for (src, dst) in &edges {
        *degree.entry(src.clone()).or_default() += 1;
        if src != dst {
            *degree.entry(dst.clone()).or_default() += 1;
        }
    }
    for (src, dst) in &edges {
        for (anchor, neighbor) in [(src, dst), (dst, src)] {
            let Some(score) = anchors.get(anchor) else {
                continue;
            };
            if anchor == neighbor {
                continue;
            }
            let degree = degree.get(neighbor).copied().unwrap_or(0);
            let hub = if degree <= 8 {
                1.
            } else {
                (8. / degree as f64).max(0.35)
            };
            let contribution = (score * 0.25).max(0.4) * hub;
            let suffix = if hub >= 1. {
                String::new()
            } else {
                format!(";hub×{hub:.2}")
            };
            if let Some(i) = position(files, neighbor) {
                files[i].score += contribution;
                add_reason(
                    &mut files[i],
                    format!("import-affinity+{contribution:.1}{suffix}"),
                );
            } else {
                files.push(RankedItem::file(
                    neighbor.as_str(),
                    contribution,
                    format!("import-affinity({anchor}{suffix})"),
                ));
            }
        }
    }
    Ok(())
}
fn matches(pattern: &str, prompt: &str) -> bool {
    regex::Regex::new(pattern)
        .expect("intent syntax")
        .is_match(prompt)
}
pub(crate) fn implementation(files: &mut [RankedItem], prompt: &str) {
    if matches(
        r"(?i)\b(test|tests|testing|failing|failure|pytest|spec)\b",
        prompt,
    ) || !matches(
        r"(?i)\b(implement(?:ed|ation|s)?|where\s+is|where\s+are|source|logic)\b",
        prompt,
    ) {
        return;
    }
    for item in files {
        if item.target.to_utf8().is_some_and(|s| is_test(&s)) {
            item.score *= 0.45;
            add_reason(item, "impl-intent×0.45".into());
        } else {
            item.score += 0.3;
            add_reason(item, "impl-intent+0.3".into());
        }
    }
}
pub(crate) fn documentation(files: &mut [RankedItem], prompt: &str) {
    if !matches(
        r"(?i)\b(install|installation|setup|configure|configuration|usage|getting started)\b",
        prompt,
    ) {
        return;
    }
    for item in files {
        if item.target.to_utf8().is_some_and(|s| {
            s.to_lowercase().ends_with(".md") || s.to_lowercase().ends_with(".rst")
        }) {
            item.score += 0.3;
            add_reason(item, "docs-intent+0.3".into());
        }
    }
}
fn parser_language(path: &str) -> Option<&str> {
    let suffix = path
        .strip_prefix("src/ken/parsers/")
        .or_else(|| path.strip_prefix("tests/parsers/test_"))?;
    let n = suffix.bytes().take_while(u8::is_ascii_lowercase).count();
    let language = &suffix[..n];
    [
        "c",
        "go",
        "java",
        "javascript",
        "python",
        "rust",
        "typescript",
    ]
    .contains(&language)
    .then_some(language)
}
pub(crate) fn language(files: &mut [RankedItem], symbols: &mut [RankedItem], prompt: &str) {
    let pattern = regex::Regex::new(r"[A-Za-z][A-Za-z0-9_+-]*").expect("language tokens");
    let words = pattern
        .find_iter(prompt)
        .map(|m| m.as_str().to_lowercase())
        .collect::<BTreeSet<_>>();
    let mut wanted = BTreeSet::new();
    for (lang, aliases) in [
        ("c", vec!["c"]),
        ("go", vec!["go", "golang"]),
        ("java", vec!["java"]),
        ("javascript", vec!["javascript", "js"]),
        ("python", vec!["python", "py"]),
        ("rust", vec!["rust", "rs"]),
        ("typescript", vec!["typescript", "ts"]),
    ] {
        if aliases.iter().any(|a| words.contains(*a)) {
            wanted.insert(lang);
        }
    }
    if wanted.is_empty() {
        return;
    }
    for (symbol, items, bonus) in [(false, files, 0.4), (true, symbols, 0.3)] {
        for item in items {
            let Some(target) = item.target.to_utf8() else {
                continue;
            };
            let path = if symbol {
                symbol_path(&target)
            } else {
                Some(target.as_str())
            };
            let Some(language) = path.and_then(parser_language) else {
                continue;
            };
            if wanted.contains(language) {
                item.score += bonus;
                add_reason(item, format!("lang-intent+{bonus:.1}"));
            } else {
                item.score *= 0.55;
                add_reason(item, "lang-intent×0.55".into());
            }
        }
    }
}
