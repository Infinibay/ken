//! Session-start narrative assembled from existing activity and knowledge.
use crate::{Result, text};
use ken_text::PythonText as Text;
use rusqlite::{Connection, OptionalExtension};
use std::path::PathBuf;
#[derive(Default)]
pub struct BriefOptions {
    pub now_ms: i64,
    pub project_root: Option<PathBuf>,
    pub checks: Vec<ken_knowledge::records::CheckObservation>,
    pub model_upgrade: Option<(String, String)>,
    pub reembed_reason: Option<String>,
}
fn notice(conn: &Connection, key: &str, now: i64) -> Result<bool> {
    let seen: Option<String> = conn
        .query_row("SELECT value FROM meta WHERE key=?", [key], |r| r.get(0))
        .optional()?;
    if seen
        .and_then(|s| s.parse::<i64>().ok())
        .is_some_and(|previous| now.saturating_sub(previous) < 7 * 86400000)
    {
        return Ok(false);
    }
    let _=conn.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",[key,&now.to_string()]);
    Ok(true)
}
fn age(delta: i64) -> String {
    if delta < 0 {
        String::new()
    } else if delta < 60000 {
        "hace instantes".into()
    } else if delta < 3600000 {
        format!("hace ~{}min", delta / 60000)
    } else if delta < 86400000 {
        format!("hace ~{}h", delta / 3600000)
    } else if delta < 30 * 86400000 {
        format!("hace ~{}d", delta / 86400000)
    } else {
        "hace tiempo".into()
    }
}
fn compact(text: &str, n: usize) -> String {
    text::compact(&text.into(), n)
        .to_utf8()
        .expect("SQLite scalar text")
}
pub fn build_session_brief(conn: &Connection, options: &BriefOptions) -> Result<Text> {
    let anchor=conn.query_row("SELECT session_id,content,created_at FROM cr_contexts WHERE kind='user_prompt' AND content<>'' ORDER BY created_at DESC,id DESC LIMIT 1",[],|r|Ok((r.get::<_,i64>(0)?,r.get::<_,String>(1)?,r.get::<_,i64>(2)?))).optional()?;
    let findings = ken_knowledge::findings::list(
        conn,
        3,
        None,
        options.project_root.as_deref(),
        &options.checks,
    )?;
    let mut model_lines = Vec::<String>::new();
    if let Some((_, recommended)) = &options.model_upgrade
        && notice(conn, "embed_upgrade_seen_at", options.now_ms).unwrap_or(false)
    {
        let short = recommended.rsplit('/').next().unwrap_or(recommended);
        model_lines.extend([String::new(),"🔔 ken: a better embedding model is available for this project.".into(),format!("   This index uses the old English-only model; the recommended one is multilingual ({short}) — same size, faster."),format!("   Upgrade without reindexing:  ken reembed --model {recommended}"),"   Tell the user they can migrate with that command, and why (better retrieval, multilingual support).".into()]);
    }
    if let Some(reason) = &options.reembed_reason
        && notice(conn, "embed_reembed_seen_at", options.now_ms).unwrap_or(false)
    {
        model_lines.extend([String::new(),"🔔 ken: this project's embeddings need re-encoding.".into(),format!("   {reason}."),"   Stored files/symbols/findings are in the query space instead of the document space, which weakens every semantic lookup.".into(),"   Fix (no reindex, no worktree needed):  ken reembed".into(),"   Tell the user to run it, and why.".into()]);
    }
    if anchor.is_none() && findings.is_empty() && model_lines.is_empty() {
        return Ok("".into());
    }
    let mut lines =
        vec!["Reanudando en este proyecto — contexto de ken (no hace falta recall):".to_owned()];
    lines.extend(model_lines);
    if let Some((session, prompt, created)) = anchor {
        let age = age(options.now_ms.saturating_sub(created));
        lines.extend([
            String::new(),
            if age.is_empty() {
                "Última sesión:".into()
            } else {
                format!("Última sesión ({age}):")
            },
            format!("  • Tarea: \"{}\"", compact(&prompt, 200)),
        ]);
        let narrative:Option<String>=conn.query_row("SELECT content FROM cr_contexts WHERE session_id=? AND kind='turn_end' AND content<>'' ORDER BY created_at DESC,id DESC LIMIT 1",[session],|r|r.get(0)).optional()?;
        if let Some(narrative) = narrative {
            lines.push(format!(
                "  • Por dónde ibas: \"{}\"",
                compact(&narrative, 220)
            ));
        }
        let mut statement=conn.prepare("SELECT target_path,SUM(CASE event_type WHEN 'edit' THEN 3 WHEN 'cited' THEN 2 WHEN 'read' THEN 1 ELSE 0 END) AS score,MAX(created_at) AS last_at FROM cr_interactions WHERE session_id=? AND target_path IS NOT NULL AND target_path<>'' GROUP BY target_path ORDER BY score DESC,last_at DESC LIMIT 5")?;
        let mut paths = Vec::new();
        for row in statement.query_map([session], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?))
        })? {
            let (path, score) = row?;
            if score == 0 {
                continue;
            }
            let shown = options
                .project_root
                .as_ref()
                .filter(|_| path.starts_with('/'))
                .and_then(|root| std::path::Path::new(&path).strip_prefix(root).ok())
                .map(|p| p.to_string_lossy().into_owned())
                .unwrap_or(path);
            paths.push(shown);
        }
        if !paths.is_empty() {
            lines.push(format!("  • Archivos en juego: {}", paths.join(", ")));
        }
    }
    if !findings.is_empty() {
        lines.extend([
            String::new(),
            format!("Findings guardados ({} recientes):", findings.len()),
        ]);
        for finding in findings {
            let line = if finding.get("justification").is_some() {
                ken_knowledge::context::brief_line(&finding, 360)
            } else {
                format!(
                    "{} — {}",
                    finding["topic"].as_str().unwrap_or(""),
                    compact(finding["content"].as_str().unwrap_or(""), 140)
                )
            };
            lines.push(format!("  • {line}"));
        }
    }
    lines.extend([
        String::new(),
        "Profundizá con ken_rank / ken_recall si seguís en esta tarea.".into(),
    ]);
    let mut inner = lines.join("\n");
    if inner.chars().count() > 1800 {
        inner = inner
            .chars()
            .take(1800)
            .collect::<String>()
            .trim_end()
            .to_owned();
        inner.push_str("\n…");
    }
    Ok(format!("<ken-session-brief>\n{inner}\n</ken-session-brief>").into())
}
