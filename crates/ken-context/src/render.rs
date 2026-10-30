//! Codepoint-bounded context delivery, independent of ranking confidence.
use crate::{RankResult, RankedItem, Result, text};
use ken_text::PythonText as Text;
use rusqlite::Connection;
use std::{collections::BTreeMap, path::PathBuf};
#[derive(Default)]
pub struct RenderOptions {
    pub verbose: i64,
    pub max_chars: Option<i64>,
    pub project_root: Option<PathBuf>,
    pub checks: Vec<ken_knowledge::records::CheckObservation>,
}
fn line(parts: impl IntoIterator<Item = Text>) -> Text {
    text::join(parts, "")
}
fn outline(conn: &Connection, path: &Text, limit: i64) -> Result<Vec<Text>> {
    let Some(path) = path.to_utf8() else {
        return Ok(Vec::new());
    };
    let mut stmt=conn.prepare("SELECT s.kind,s.name,s.qualname,s.line_start,s.docstring FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id WHERE f.path=? ORDER BY s.line_start LIMIT ?")?;
    let mut lines = Vec::new();
    for row in stmt.query_map(rusqlite::params![path, limit], |r| {
        Ok((
            r.get::<_, String>(0)?,
            r.get::<_, String>(2)?,
            r.get::<_, i64>(3)?,
            r.get::<_, Option<String>>(4)?,
        ))
    })? {
        let (kind, qual, line, doc) = row?;
        let mut result: Text = format!("{kind} {qual} (line {line})").into();
        let doc = text::compact(&doc.unwrap_or_default().into(), 96);
        if !doc.is_empty() {
            result = text::append(&result, " — ", doc);
        }
        lines.push(result);
    }
    Ok(lines)
}
fn channel_summary(reason: &Text, finding_item: bool) -> String {
    let reason = text::matching(reason);
    let (mut semantic, mut recentness, mut dependency, mut finding) = (0f64, 0f64, 0f64, 0f64);
    let values = |pattern: &str| {
        let re = regex::Regex::new(pattern).expect("channel annotation syntax");
        re.captures_iter(&reason)
            .filter_map(|c| c[1].parse::<f64>().ok())
            .collect::<Vec<_>>()
    };
    for value in values(r"fuzzy:([0-9.]+)")
        .into_iter()
        .chain(values(r"doc-intent(?:-symbol)?:[^:|+]+:([0-9.]+)"))
    {
        semantic = semantic.max(value);
    }
    if reason.contains("explicit-mention") || reason.contains("explicit-symbol-mention") {
        semantic = semantic.max(1.);
    }
    if reason.contains("explicit-line-mention") {
        semantic = semantic.max(0.9);
    }
    if reason.contains("lexical") {
        semantic = semantic.max(0.6);
    }
    if reason.contains("reactive:") || reason.contains("predictive") {
        semantic = semantic.max(0.5);
    }
    if let Some(value) = values(r"fresh×([0-9.]+)").first() {
        recentness = (value - 1.).max(0.);
    }
    for value in values(r"(?:symbol-file|import-affinity|test-affinity|cooc)\+([0-9.]+)") {
        dependency += value;
    }
    if [
        "symbol-file(",
        "import-affinity(",
        "test-affinity(",
        "cooc(",
    ]
    .iter()
    .any(|marker| reason.contains(marker))
    {
        dependency = dependency.max(0.4);
    }
    if let Some(value) = values(r"finding:([0-9.]+)").first() {
        finding = *value;
    } else if finding_item {
        finding = 1.;
    }
    format!(
        "semantic_relevance={semantic:.2}, recentness={recentness:.2}, dependency_affinity={dependency:.1}, remembered_finding={finding:.2}"
    )
}
fn ranked_line(item: &RankedItem, index: usize, priority: bool) -> Text {
    let suffix = if priority {
        let priority = if index == 1 {
            "open-first"
        } else if index <= 3 {
            "open-early"
        } else {
            "secondary"
        };
        format!(
            "  [{priority}; score={:.1}; {}] — ",
            item.score,
            channel_summary(&item.reason, false)
        )
    } else {
        format!("  [score={:.1}] — ", item.score)
    };
    line([
        format!("  {index}. ").into(),
        item.target.clone(),
        suffix.into(),
        item.reason.clone(),
    ])
}
pub fn render_block(
    conn: &Connection,
    result: &RankResult,
    options: &RenderOptions,
) -> Result<Text> {
    if result.empty() {
        return Ok("".into());
    }
    let (level, max_files, outline_n, max_symbols, max_findings) = match options.verbose {
        0 => (0, 3, 0, 2, 1),
        2 => (2, 8, 12, 5, 3),
        _ => (1, 5, 3, 5, 3),
    };
    let mut lines = Vec::<Text>::new();
    if level == 0 {
        lines.extend(["<context-rank>".into(), "Relevant context:".into()]);
        for (header, items, limit) in [
            ("Files:", &result.files, max_files),
            ("Symbols:", &result.symbols, max_symbols),
        ] {
            if !items.is_empty() {
                lines.push(header.into());
                for item in items.iter().take(limit) {
                    lines.push(line(["- ".into(), item.target.clone()]));
                }
            }
        }
        if !result.findings.is_empty() {
            lines.push("Notes:".into());
            for finding in result.findings.iter().take(max_findings) {
                lines.push(line(["- ".into(), finding.topic.clone()]));
            }
        }
    } else {
        lines.extend([
            format!("<context-rank verbose={level}>").into(),
            "Likely relevant resources.".into(),
        ]);
        let mut outlines = Vec::new();
        if !result.files.is_empty() {
            lines.extend(["".into(), "Files (by relevance):".into()]);
            for (i, item) in result.files.iter().take(max_files).enumerate() {
                lines.push(ranked_line(item, i + 1, true));
                let rows = outline(conn, &item.target, outline_n)?;
                if !rows.is_empty() {
                    outlines.push((item.target.clone(), rows));
                }
            }
        }
        if !result.symbols.is_empty() {
            lines.extend(["".into(), "Symbols:".into()]);
            for (i, item) in result.symbols.iter().take(max_symbols).enumerate() {
                lines.push(ranked_line(item, i + 1, false));
            }
        }
        if !result.findings.is_empty() {
            let topics = result
                .findings
                .iter()
                .take(max_findings)
                .filter_map(|f| f.topic.to_utf8())
                .collect::<Vec<_>>();
            let memories = ken_knowledge::records::for_topics(
                conn,
                &topics,
                options.project_root.as_deref(),
                &options.checks,
            )?
            .into_iter()
            .filter_map(|m| m["topic"].as_str().map(|s| (s.to_owned(), m.clone())))
            .collect::<BTreeMap<_, _>>();
            lines.extend(["".into(), "Findings:".into()]);
            for (i, finding) in result.findings.iter().take(max_findings).enumerate() {
                let tags = if finding.tags.is_empty() {
                    "".into()
                } else {
                    line([
                        " [".into(),
                        text::join(finding.tags.clone(), " "),
                        "]".into(),
                    ])
                };
                let decoded = finding
                    .tags
                    .iter()
                    .filter_map(Text::to_utf8)
                    .collect::<Vec<_>>();
                let (kind, _) = ken_knowledge::findings::classify_tags(&decoded);
                lines.push(line([
                    format!("  {}. ", i + 1).into(),
                    finding.topic.clone(),
                    tags,
                    format!(
                        "  [type={kind}; score={:.1}; {}] — ",
                        finding.score,
                        channel_summary(&finding.reason, true)
                    )
                    .into(),
                    finding.reason.clone(),
                ]));
                let content = finding
                    .topic
                    .to_utf8()
                    .and_then(|t| memories.get(&t))
                    .filter(|m| m.get("justification").is_some())
                    .map(|m| ken_knowledge::context::brief_line(m, 220).into())
                    .unwrap_or_else(|| text::compact(&finding.content, 220));
                lines.push(line(["       ".into(), content]));
            }
        }
        if !outlines.is_empty() {
            lines.extend(["".into(), "Outlines:".into()]);
            for (path, rows) in outlines {
                lines.push(line(["  ".into(), path, ":".into()]));
                for row in rows {
                    lines.push(line(["       ".into(), row]));
                }
            }
        }
    }
    lines.push("</context-rank>".into());
    Ok(fit(text::join(lines, "\n"), options.max_chars))
}
fn fit(block: Text, max: Option<i64>) -> Text {
    let Some(max) = max.filter(|m| *m > 0).map(|m| m as usize) else {
        return block;
    };
    if block.codepoints().len() <= max {
        return block;
    }
    let lines = text::splitlines(&block);
    if lines.len() <= 2
        || lines.last().and_then(Text::to_utf8).as_deref() != Some("</context-rank>")
    {
        return Text::from_codepoints(
            block.codepoints()[..max.min(block.codepoints().len())].to_vec(),
        )
        .unwrap();
    }
    let first = lines[0].clone();
    let footer: Text = "</context-rank>".into();
    if text::join([first.clone(), footer.clone()], "\n")
        .codepoints()
        .len()
        > max
    {
        return "".into();
    }
    let mut marker: Text =
        "(truncated by context budget; call ken_rank(verbose=2) to expand.)".into();
    if text::join([first.clone(), marker.clone(), footer.clone()], "\n")
        .codepoints()
        .len()
        > max
    {
        marker = "(truncated)".into();
    }
    if text::join([first.clone(), marker.clone(), footer.clone()], "\n")
        .codepoints()
        .len()
        > max
    {
        return text::join([first, footer], "\n");
    }
    let mut kept = vec![first];
    for candidate in &lines[1..lines.len() - 1] {
        let mut next = kept.clone();
        next.extend([candidate.clone(), marker.clone(), footer.clone()]);
        if text::join(next, "\n").codepoints().len() > max {
            break;
        }
        kept.push(candidate.clone());
    }
    kept.extend([marker, footer]);
    text::join(kept, "\n")
}
pub fn visible_file_paths(block: &Text) -> Vec<Text> {
    let mut in_files = false;
    let mut out = Vec::new();
    for line in text::splitlines(block) {
        if line.to_utf8().as_deref() == Some("Files:") {
            in_files = true;
        } else if in_files {
            if line.codepoints().starts_with(&[45, 32]) {
                out.push(Text::from_codepoints(line.codepoints()[2..].to_vec()).unwrap());
            } else {
                break;
            }
        }
    }
    out
}
