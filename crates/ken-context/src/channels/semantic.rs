use crate::{Clock, ContextNumerics, Error, FindingItem, Policy, RankedItem, Result};
use rusqlite::{Connection, params_from_iter};
use std::{collections::BTreeMap, path::Path};
#[derive(Clone)]
struct Row {
    slot: Option<i64>,
    path: String,
    qualname: Option<String>,
    line: i64,
    kind: String,
    weight: f64,
    mtime: i64,
    blob: Option<Vec<u8>>,
}
fn columns(space: &str) -> (&'static str, &'static str, &'static str) {
    match space {
        "ci_files" => (
            "SELECT vec_slot,path,NULL,0,'',1.0,mtime,embedding FROM ci_files",
            "vec_slot",
            "embedding",
        ),
        "ci_symbols" => (
            "SELECT s.vec_slot,f.path,s.qualname,s.line_start,'',1.0,f.mtime,s.embedding FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id",
            "s.vec_slot",
            "s.embedding",
        ),
        _ => (
            "SELECT i.vec_slot,f.path,s.qualname,s.line_start,i.source_kind,i.weight,0,i.embedding FROM ci_intent_sources i JOIN ci_files f ON f.id=i.file_id LEFT JOIN ci_symbols s ON s.id=i.symbol_id",
            "i.vec_slot",
            "i.embedding",
        ),
    }
}
fn row(r: &rusqlite::Row<'_>) -> rusqlite::Result<Row> {
    Ok(Row {
        slot: r.get(0)?,
        path: r.get(1)?,
        qualname: r.get(2)?,
        line: r.get::<_, Option<i64>>(3)?.unwrap_or(0),
        kind: r.get(4)?,
        weight: r.get(5)?,
        mtime: r.get(6)?,
        blob: r.get(7)?,
    })
}
#[expect(
    clippy::too_many_arguments,
    reason = "Keep the channel's query, source, threshold policy and numerical owner explicit."
)]
fn pairs(
    conn: &Connection,
    space: &str,
    q: &[f32],
    root: Option<&Path>,
    fixed: f64,
    headroom: f64,
    policy: &Policy,
    numerics: &mut dyn ContextNumerics,
) -> Result<(Vec<(Row, f64)>, f64)> {
    let (base, slot, embedding) = columns(space);
    if let Some(live) = numerics.live_scores(conn, root, space, q)? {
        if live.slots.len() != live.scores.len()
            || live
                .slots
                .iter()
                .collect::<std::collections::BTreeSet<_>>()
                .len()
                != live.slots.len()
        {
            return Err(Error::Invalid(
                "context numerical provider returned incompatible live slots".into(),
            ));
        }
        let threshold = numerics.adaptive_threshold(&live.scores, fixed, policy.adaptive)?;
        let selected =
            numerics.capped_indices(&live.scores, threshold, headroom, policy.fuzzy_resolve_cap)?;
        let mut unique = std::collections::BTreeSet::new();
        if selected
            .iter()
            .any(|i| *i >= live.slots.len() || !unique.insert(*i))
        {
            return Err(Error::Invalid(
                "context numerical provider returned incompatible candidate indices".into(),
            ));
        }
        let mut rows = BTreeMap::new();
        for chunk in selected.chunks(500) {
            let values = chunk.iter().map(|i| live.slots[*i]).collect::<Vec<_>>();
            if values.is_empty() {
                continue;
            }
            let sql = format!(
                "{base} WHERE {slot} IN ({})",
                vec!["?"; values.len()].join(",")
            );
            let mut stmt = conn.prepare(&sql)?;
            for found in stmt.query_map(params_from_iter(values), row)? {
                let row = found?;
                if let Some(slot) = row.slot {
                    rows.insert(slot, row);
                }
            }
        }
        return Ok((
            selected
                .into_iter()
                .filter_map(|i| {
                    rows.get(&live.slots[i])
                        .cloned()
                        .map(|row| (row, f64::from(live.scores[i])))
                })
                .collect(),
            threshold,
        ));
    }
    let mut stmt = conn.prepare(&format!("{base} WHERE {embedding} IS NOT NULL"))?;
    let rows = stmt
        .query_map([], row)?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    if rows.is_empty() {
        return Ok((Vec::new(), fixed));
    }
    let blobs = rows
        .iter()
        .map(|r| r.blob.clone().unwrap_or_default())
        .collect::<Vec<_>>();
    let ranked = super::inline(numerics, q, &blobs)?;
    let threshold = numerics.adaptive_threshold(&ranked.scores, fixed, policy.adaptive)?;
    Ok((
        ranked
            .kept
            .into_iter()
            .zip(ranked.scores)
            .map(|(i, s)| (rows[i].clone(), f64::from(s)))
            .collect(),
        threshold,
    ))
}
fn bump(mtime: i64, clock: &Clock) -> f64 {
    let days = ((clock.now_ns as f64 - mtime as f64) / 1e9 / 86400.).max(0.);
    if days >= 14. {
        0.
    } else {
        0.1 * (1. - days / 14.)
    }
}
pub fn fuzzy_scores(
    conn: &Connection,
    q: &[f32],
    root: Option<&Path>,
    clock: &Clock,
    policy: &Policy,
    numerics: &mut dyn ContextNumerics,
) -> Result<(Vec<RankedItem>, Vec<RankedItem>)> {
    let q = numerics.normalize_query(q)?;
    let mut out = [Vec::new(), Vec::new()];
    for (index, space, fixed, scale, bonus) in [
        (0, "ci_files", 0.40, 4.5, 0.),
        (1, "ci_symbols", 0.45, 5., 0.5),
    ] {
        let (pairs, threshold) = pairs(conn, space, &q, root, fixed, 0.1, policy, numerics)?;
        for (row, similarity) in pairs {
            let bump = bump(row.mtime, clock);
            let s = (similarity + bump).min(1.);
            if s < threshold {
                continue;
            }
            let score = (s - threshold) * scale / (1. - threshold) + bonus;
            let mut reason = format!("fuzzy:{similarity:.2}");
            if bump > 0. {
                reason.push_str(&format!("+recent{bump:.2}"));
            }
            out[index].push(if index == 0 {
                RankedItem::file(row.path, score, reason)
            } else {
                RankedItem::symbol(
                    format!(
                        "{} ({}:{})",
                        row.qualname.unwrap_or_default(),
                        row.path,
                        row.line
                    ),
                    score,
                    reason,
                )
            });
        }
    }
    let [files, symbols] = out;
    Ok((files, symbols))
}
fn keep_best(items: &mut Vec<RankedItem>, item: RankedItem) {
    if let Some(old) = items.iter_mut().find(|i| i.target == item.target) {
        if item.score > old.score {
            *old = item;
        }
    } else {
        items.push(item);
    }
}
pub fn doc_intent_scores(
    conn: &Connection,
    q: &[f32],
    root: Option<&Path>,
    policy: &Policy,
    numerics: &mut dyn ContextNumerics,
) -> Result<(Vec<RankedItem>, Vec<RankedItem>)> {
    let q = numerics.normalize_query(q)?;
    let (pairs, threshold) = pairs(
        conn,
        "ci_intent_sources",
        &q,
        root,
        0.42,
        0.,
        policy,
        numerics,
    )?;
    let (mut files, mut symbols) = (Vec::new(), Vec::new());
    for (row, similarity) in pairs {
        if similarity < threshold {
            continue;
        }
        if let Some(qualname) = row.qualname {
            let score = (similarity - threshold) * 3.6 / (1. - threshold) * row.weight;
            keep_best(
                &mut symbols,
                RankedItem::symbol(
                    format!("{qualname} ({}:{})", row.path, row.line),
                    score,
                    format!("doc-intent:{}:{similarity:.2}", row.kind),
                ),
            );
            keep_best(
                &mut files,
                RankedItem::file(
                    row.path,
                    score * 0.65,
                    format!("doc-intent-symbol:{}:{similarity:.2}", row.kind),
                ),
            );
        } else {
            keep_best(
                &mut files,
                RankedItem::file(
                    row.path,
                    (similarity - threshold) * 3.2 / (1. - threshold) * row.weight,
                    format!("doc-intent:{}:{similarity:.2}", row.kind),
                ),
            );
        }
    }
    Ok((files, symbols))
}
pub fn finding_scores(
    conn: &Connection,
    q: &[f32],
    numerics: &mut dyn ContextNumerics,
) -> Result<Vec<FindingItem>> {
    let mut stmt = conn.prepare(
        "SELECT topic,content,tags,embedding FROM cr_findings WHERE embedding IS NOT NULL",
    )?;
    let rows = stmt
        .query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, Option<String>>(2)?,
                r.get::<_, Vec<u8>>(3)?,
            ))
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    if rows.is_empty() {
        return Ok(Vec::new());
    }
    let ranked = super::inline(
        numerics,
        q,
        &rows.iter().map(|r| r.3.clone()).collect::<Vec<_>>(),
    )?;
    Ok(ranked
        .kept
        .into_iter()
        .zip(ranked.scores)
        .filter_map(|(i, sim)| {
            let sim = f64::from(sim);
            if sim < 0.48 {
                return None;
            }
            let row = &rows[i];
            let tags = row
                .2
                .as_deref()
                .and_then(|s| serde_json::from_str::<serde_json::Value>(s).ok())
                .and_then(|v| v.as_array().cloned())
                .unwrap_or_default()
                .into_iter()
                .filter_map(|v| v.as_str().map(Into::into))
                .collect();
            Some(FindingItem {
                topic: row.0.as_str().into(),
                content: row.1.as_str().into(),
                tags,
                score: (sim - 0.48) * 3.5 / (1. - 0.48),
                reason: format!("finding:{sim:.2}").into(),
            })
        })
        .collect())
}
