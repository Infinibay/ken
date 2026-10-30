//! Mapped live-slot scoring. SQLite owns liveness, ken-store owns physical
//! segments, and NativeVectorMath owns normalization and BLAS arithmetic.
use crate::{
    Result, RetrievalError,
    vector_math::{NativeVectorMath, QueryNorm},
};
use ken_store::{VectorSpace, VectorStore, high_water};
use rusqlite::Connection;
use std::{collections::BTreeSet, path::Path};
#[derive(Clone, Debug)]
pub struct LiveScores {
    pub slots: Vec<i64>,
    pub scores: Vec<f32>,
}
pub fn live_store_scores(
    conn: &Connection,
    root: Option<&Path>,
    space: VectorSpace,
    query: &[f32],
    math: &NativeVectorMath,
) -> Result<Option<LiveScores>> {
    let Some(root) = root else { return Ok(None) };
    let context = ken_core::project::DiscoveryContext::from_process()
        .map_err(|e| RetrievalError::Invalid(e.to_string()))?;
    let paths = ken_core::project::ProjectPaths::at(root, &context)
        .map_err(|e| RetrievalError::Invalid(e.to_string()))?;
    let directory = paths
        .resolve_inside(Path::new(".ken/vectors"), &context)
        .map_err(|e| RetrievalError::Invalid(e.to_string()))?;
    if !directory.is_dir() || !directory.join(format!("{}.json", space.as_str())).is_file() {
        return Ok(None);
    }
    let store = match VectorStore::open(&directory, space, query.len(), None) {
        Ok(store) => store,
        Err(_) => return Ok(None),
    };
    let count = high_water(conn, space)?;
    if count <= 0 {
        return Ok(None);
    }
    let count = usize::try_from(count)
        .map_err(|_| RetrievalError::Invalid("vector high-water exceeds address space".into()))?;
    let query = math.normalize_query(query, QueryNorm::ClampEpsilon(1e-12))?;
    let segment_rows = store.manifest().segment_rows;
    let mut all = Vec::new();
    all.try_reserve_exact(count)
        .map_err(|_| RetrievalError::Invalid("vector score allocation exceeds memory".into()))?;
    for start in (0..count).step_by(segment_rows) {
        let end = count.min(start.saturating_add(segment_rows));
        let slots = (start..end).map(|i| i as i64).collect::<Vec<_>>();
        let rows = match store.read(&slots) {
            Ok(rows) => rows,
            Err(_) => return Ok(None),
        };
        let matrix = rows.into_iter().flatten().collect::<Vec<_>>();
        all.extend(math.scores(&matrix, end - start, query.len(), &query)?);
    }
    let mut statement = conn.prepare("SELECT slot FROM ci_vec_free WHERE space=?")?;
    let free = statement
        .query_map([space.as_str()], |r| r.get::<_, i64>(0))?
        .collect::<rusqlite::Result<BTreeSet<_>>>()?;
    let mut result = LiveScores {
        slots: Vec::new(),
        scores: Vec::new(),
    };
    for (slot, score) in all.into_iter().enumerate() {
        if !free.contains(&(slot as i64)) {
            result.slots.push(slot as i64);
            result.scores.push(score);
        }
    }
    Ok(Some(result))
}
