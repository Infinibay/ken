use crate::{RankedItem, Result, text};
use ken_retrieval::vocabulary::{NAME_TOKEN_VERSION, name_tokens};
use ken_text::PythonText;
use rusqlite::{Connection, OptionalExtension, params_from_iter, types::Value};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
};
#[derive(Default)]
struct Overlaps {
    order: Vec<i64>,
    by_id: BTreeMap<i64, BTreeSet<String>>,
}
fn overlaps(conn: &Connection, kind: i64, tokens: &BTreeSet<String>) -> Result<Overlaps> {
    let mut out = Overlaps::default();
    let values = tokens.iter().collect::<Vec<_>>();
    for chunk in values.chunks(500) {
        let mut params = vec![Value::Integer(kind)];
        params.extend(chunk.iter().map(|s| Value::Text((*s).clone())));
        let mut stmt = conn.prepare(&format!(
            "SELECT row_id,token FROM ci_name_tokens WHERE kind=? AND token IN ({})",
            vec!["?"; chunk.len()].join(",")
        ))?;
        for row in stmt.query_map(params_from_iter(params), |r| {
            Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?))
        })? {
            let (id, token) = row?;
            if !out.by_id.contains_key(&id) {
                out.order.push(id);
            }
            out.by_id.entry(id).or_default().insert(token);
        }
    }
    Ok(out)
}
fn file_rows(conn: &Connection, hits: Option<&Overlaps>) -> Result<Vec<(i64, String)>> {
    if let Some(hits) = hits {
        let ids = hits.by_id.keys().copied().collect::<Vec<_>>();
        let mut paths = BTreeMap::new();
        for chunk in ids.chunks(500) {
            let mut stmt = conn.prepare(&format!(
                "SELECT id,path FROM ci_files WHERE id IN ({})",
                vec!["?"; chunk.len()].join(",")
            ))?;
            for row in stmt.query_map(params_from_iter(chunk), |r| {
                Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?))
            })? {
                let (id, path) = row?;
                paths.insert(id, path);
            }
        }
        return Ok(hits
            .order
            .iter()
            .filter_map(|id| paths.remove(id).map(|p| (*id, p)))
            .collect());
    }
    let mut stmt = conn.prepare("SELECT id,path FROM ci_files")?;
    Ok(stmt
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?
        .collect::<rusqlite::Result<_>>()?)
}
struct Symbol {
    id: i64,
    kind: String,
    qualname: String,
    name: String,
    line: i64,
    path: String,
}
fn symbol_rows(conn: &Connection, hits: Option<&Overlaps>) -> Result<Vec<Symbol>> {
    let base = "SELECT s.id,s.kind,s.qualname,s.name,s.line_start,f.path FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id";
    let parse = |r: &rusqlite::Row<'_>| {
        Ok(Symbol {
            id: r.get(0)?,
            kind: r.get::<_, Option<String>>(1)?.unwrap_or_default(),
            qualname: r.get::<_, Option<String>>(2)?.unwrap_or_default(),
            name: r.get(3)?,
            line: r.get(4)?,
            path: r.get(5)?,
        })
    };
    let mut out = Vec::new();
    if let Some(hits) = hits {
        let ids = hits.by_id.keys().copied().collect::<Vec<_>>();
        for chunk in ids.chunks(500) {
            let mut stmt = conn.prepare(&format!(
                "{base} WHERE s.id IN ({})",
                vec!["?"; chunk.len()].join(",")
            ))?;
            out.extend(
                stmt.query_map(params_from_iter(chunk), parse)?
                    .collect::<rusqlite::Result<Vec<_>>>()?,
            );
        }
    } else {
        let mut stmt = conn.prepare(base)?;
        out.extend(
            stmt.query_map([], parse)?
                .collect::<rusqlite::Result<Vec<_>>>()?,
        );
    }
    Ok(out)
}
fn query_tokens(
    conn: &Connection,
    prompt: &str,
    agent: Option<&str>,
    stops: &BTreeSet<String>,
) -> Result<(BTreeSet<String>, &'static str, f64)> {
    let mut tokens = name_tokens(prompt, stops);
    let mut prefix = "lexical";
    let mut bonus = 0.;
    let continuation=regex::Regex::new(r"(?i)\b(continue|continuing|keep going|carry on|resume|sigue|seguir|continua|continuar|contin[uú]a|segu[ií]|seguimos)\b").expect("continuation syntax");
    if agent.is_some_and(|a| !a.is_empty()) && (tokens.is_empty() || continuation.is_match(prompt))
    {
        let session: Option<i64> = conn
            .query_row(
                "SELECT id FROM cr_sessions WHERE agent_id=?",
                [agent.unwrap()],
                |r| r.get(0),
            )
            .optional()?;
        if let Some(session) = session {
            let mut stmt=conn.prepare("SELECT content FROM cr_contexts WHERE session_id=? AND kind='user_prompt' ORDER BY id DESC LIMIT 4")?;
            let mut context = BTreeSet::new();
            let (mut skipped, mut used) = (false, 0);
            for content in stmt.query_map([session], |r| r.get::<_, String>(0))? {
                let content = content?;
                if !skipped && content == prompt {
                    skipped = true;
                    continue;
                }
                context.extend(name_tokens(&content, stops));
                used += 1;
                if used >= 3 {
                    break;
                }
            }
            if !context.is_empty() {
                tokens.extend(context);
                prefix = "lexical-context";
                bonus = 0.6;
            }
        }
    }
    Ok((tokens, prefix, bonus))
}
pub fn lexical_scores(
    conn: &Connection,
    prompt: &PythonText,
    agent: Option<&str>,
    root: Option<&Path>,
) -> Result<(Vec<RankedItem>, Vec<RankedItem>)> {
    let stops = root
        .and_then(Path::file_name)
        .map(|s| name_tokens(&s.to_string_lossy(), &BTreeSet::new()))
        .unwrap_or_default();
    let (tokens, prefix, bonus) = query_tokens(conn, &text::matching(prompt), agent, &stops)?;
    if tokens.is_empty() {
        return Ok((Vec::new(), Vec::new()));
    }
    let posting = conn
        .query_row(
            "SELECT value FROM meta WHERE key='name_token_version'",
            [],
            |r| r.get::<_, String>(0),
        )
        .optional()
        .ok()
        .flatten()
        == Some(NAME_TOKEN_VERSION.to_string());
    let file_hits = if posting {
        Some(overlaps(conn, 0, &tokens)?)
    } else {
        None
    };
    let symbol_hits = if posting {
        Some(overlaps(conn, 1, &tokens)?)
    } else {
        None
    };
    let mut files = Vec::new();
    for (id, path) in file_rows(conn, file_hits.as_ref())? {
        let overlap = if let Some(hits) = &file_hits {
            hits.by_id.get(&id).cloned().unwrap_or_default()
        } else {
            tokens
                .intersection(&name_tokens(&path, &stops))
                .cloned()
                .collect()
        };
        if overlap.is_empty() {
            continue;
        }
        let score = (0.6 + 0.4 * overlap.len() as f64 + bonus).min(1.4 + bonus);
        files.push(RankedItem::file(
            path,
            score,
            format!(
                "{prefix}:{}",
                overlap.into_iter().take(3).collect::<Vec<_>>().join(",")
            ),
        ));
    }
    let mut symbols = Vec::new();
    for row in symbol_rows(conn, symbol_hits.as_ref())? {
        let overlap = if let Some(hits) = &symbol_hits {
            hits.by_id.get(&row.id).cloned().unwrap_or_default()
        } else {
            tokens
                .intersection(&name_tokens(
                    &format!("{} {} {}", row.kind, row.qualname, row.name),
                    &stops,
                ))
                .cloned()
                .collect()
        };
        if overlap.is_empty() {
            continue;
        }
        let exact = row.name.trim_matches('_').to_lowercase();
        let exact_bonus = if tokens.contains(&exact)
            && ![
                "chars", "class", "code", "context", "file", "source", "stats", "test",
            ]
            .contains(&exact.as_str())
        {
            1.
        } else {
            0.
        };
        let kind_bonus = if tokens.contains(&row.kind.to_lowercase()) {
            1.2
        } else {
            0.
        };
        let score = (0.8 + 0.5 * overlap.len() as f64 + exact_bonus + kind_bonus + bonus)
            .min(1.8 + 1. + 1.2 + bonus);
        let mut reason = format!(
            "{prefix}:{}",
            overlap.into_iter().take(3).collect::<Vec<_>>().join(",")
        );
        if exact_bonus > 0. {
            reason.push_str("+exact");
        }
        if kind_bonus > 0. {
            reason.push_str("+kind");
        }
        symbols.push(RankedItem::symbol(
            format!("{} ({}:{})", row.qualname, row.path, row.line),
            score,
            reason,
        ));
    }
    Ok((files, symbols))
}
