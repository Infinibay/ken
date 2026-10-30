//! Stored documentation selects a bounded candidate set; it never supplies the
//! current documentation used by responsibility reasoners.
use crate::{IndexedCandidate, ResponsibilityVectors, Result, invalid, reasoners};
use rusqlite::Connection;
use std::{collections::BTreeMap, path::Path};
fn is_test(path: &str, name: &str) -> bool {
    Path::new(path)
        .components()
        .any(|p| ["tests", "test", "__tests__"].contains(&p.as_os_str().to_string_lossy().as_ref()))
        || Path::new(path)
            .file_stem()
            .is_some_and(|p| p.to_string_lossy().starts_with("test_"))
        || name.starts_with("test_")
}
pub fn similarities(
    conn: &Connection,
    root: &Path,
    rows: &[IndexedCandidate],
    queries: &[Vec<f32>],
    vectors: &mut dyn ResponsibilityVectors,
) -> Result<Vec<BTreeMap<usize, f32>>> {
    let mut result = Vec::new();
    for query in queries {
        let live = vectors.live_scores(conn, root, query)?;
        let mut slots = BTreeMap::new();
        if let Some(live) = live {
            if live.slots.len() != live.scores.len() {
                return Err(invalid("mapped responsibility score counts do not align"));
            }
            slots.extend(live.slots.into_iter().zip(live.scores));
        }
        let mut values = BTreeMap::new();
        for (index, row) in rows.iter().enumerate() {
            if let Some(score) = row.vec_slot.and_then(|slot| slots.get(&slot)) {
                values.insert(index, *score);
            }
        }
        let missing = rows
            .iter()
            .enumerate()
            .filter(|(i, row)| !values.contains_key(i) && row.embedding.is_some())
            .map(|(i, _)| i)
            .collect::<Vec<_>>();
        let blobs = missing
            .iter()
            .map(|i| {
                rows[*i]
                    .embedding
                    .as_ref()
                    .expect("filtered embedding")
                    .clone()
            })
            .collect::<Vec<_>>();
        let ranked = vectors.rank_against(query, &blobs)?;
        if ranked.kept.len() != ranked.scores.len()
            || ranked.kept.iter().any(|i| *i >= missing.len())
        {
            return Err(invalid("inline responsibility score counts do not align"));
        }
        for (index, score) in ranked.kept.into_iter().zip(ranked.scores) {
            values.insert(missing[index], score);
        }
        result.push(values);
    }
    Ok(result)
}
pub(crate) fn retrieve(
    conn: &Connection,
    root: &Path,
    scope: &Path,
    formulations: &[String],
    queries: &[Vec<f32>],
    include_tests: bool,
    vectors: &mut dyn ResponsibilityVectors,
) -> Result<(Vec<IndexedCandidate>, usize)> {
    let mut query=conn.prepare("SELECT s.qualname,s.kind,s.name,s.docstring,f.path,f.content_hash,i.vec_slot,i.embedding FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id LEFT JOIN ci_intent_sources i ON i.symbol_id=s.id AND i.source_kind='symbol_docstring' WHERE s.kind IN ('function','method','class') UNION ALL SELECT f.path AS qualname,'module' AS kind,f.path AS name,i.text AS docstring,f.path,f.content_hash,i.vec_slot,i.embedding FROM ci_intent_sources i JOIN ci_files f ON f.id=i.file_id WHERE i.source_kind='module_docstring' AND i.symbol_id IS NULL ORDER BY path,kind,qualname")?;
    let rows = query
        .query_map([], |r| {
            Ok(IndexedCandidate {
                qualname: r.get(0)?,
                kind: r.get(1)?,
                name: r.get(2)?,
                docstring: r.get(3)?,
                path: r.get(4)?,
                content_hash: r.get(5)?,
                vec_slot: r.get(6)?,
                embedding: r.get(7)?,
            })
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    let rows = rows
        .into_iter()
        .filter(|r| {
            root.join(&r.path).starts_with(scope)
                && (include_tests || !is_test(&r.path, &r.qualname))
        })
        .collect::<Vec<_>>();
    let scores = similarities(conn, root, &rows, queries, vectors)?;
    let terms = formulations
        .iter()
        .map(|f| reasoners::terms(f))
        .collect::<Vec<_>>();
    let mut ranked = rows
        .into_iter()
        .enumerate()
        .map(|(index, row)| {
            let score = terms
                .iter()
                .enumerate()
                .map(|(j, t)| {
                    f64::from(*scores[j].get(&index).unwrap_or(&0.))
                        .max(0.85 * reasoners::overlap(t, row.docstring.as_deref().unwrap_or("")))
                        .max(0.65 * reasoners::overlap(t, &row.qualname))
                })
                .fold(f64::NEG_INFINITY, f64::max);
            (score, row)
        })
        .collect::<Vec<_>>();
    let count = ranked.len();
    ranked.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
    Ok((
        ranked.into_iter().take(40).map(|(_, row)| row).collect(),
        count,
    ))
}
