//! Prompt-to-outcome aggregation. Embedding, cosine and argsort belong to the
//! injected native numerical owner, including its float32 and tie semantics.
use crate::{HistoryError, Result, positive_limit, rounded};
use rusqlite::{Connection, params};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::Path,
};

pub struct Ranking {
    pub scores: Vec<f32>,
    /// Complete `argsort(-scores)` permutation, supplied by the numerical owner.
    pub order: Vec<usize>,
}
pub trait IntentVectors {
    fn embed_query(&mut self, query: &str) -> Result<Vec<f32>>;
    fn rank(&mut self, query: &[f32], rows: &[Vec<f32>]) -> Result<Ranking>;
}
struct Prompt {
    id: i64,
    content: Option<String>,
    vector: Vec<u8>,
}
struct FileOutcome {
    path: String,
    score: f64,
    hits: usize,
    sessions: BTreeSet<i64>,
}

pub fn intent_history(
    conn: &Connection,
    query: &str,
    k_prompts: i64,
    limit: i64,
    root: Option<&Path>,
    vectors: &mut dyn IntentVectors,
) -> Result<Value> {
    let mut statement = conn.prepare("SELECT id,session_id,content,embedding FROM cr_contexts WHERE kind='user_prompt' AND embedding IS NOT NULL")?;
    let prompts = statement
        .query_map([], |row| {
            Ok(Prompt {
                id: row.get(0)?,
                content: row.get(2)?,
                vector: row.get(3)?,
            })
        })?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    let empty = |note: &str| json!({"ok":true,"query":query,"files":[],"note":note});
    if prompts.is_empty() {
        return Ok(empty("no embedded prompt history yet"));
    }
    let query_vector = vectors.embed_query(query)?;
    let mut retained = Vec::new();
    let mut rows = Vec::new();
    for prompt in prompts {
        if prompt.vector.len() % 4 != 0 {
            return Err(HistoryError::Invalid(
                "stored prompt vector byte length is not a multiple of float32 size".into(),
            ));
        }
        if prompt.vector.len() / 4 != query_vector.len() {
            continue;
        }
        rows.push(
            prompt
                .vector
                .chunks_exact(4)
                .map(|b| f32::from_le_bytes(b.try_into().expect("four bytes")))
                .collect(),
        );
        retained.push(prompt);
    }
    if retained.is_empty() {
        return Ok(empty(
            "stored prompt vectors predate the current embedding model",
        ));
    }
    let ranking = vectors.rank(&query_vector, &rows)?;
    if ranking.scores.len() != rows.len()
        || ranking.order.len() != rows.len()
        || ranking.order.iter().copied().collect::<BTreeSet<_>>() != (0..rows.len()).collect()
    {
        return Err(HistoryError::Invalid(
            "intent ranking must supply one score per row and a complete row permutation".into(),
        ));
    }
    // np.float32 scalar comparison preserves the 0.2f32 boundary. Promoting
    // the score to f64 first would accidentally admit that boundary value.
    let matched: Vec<_> = ranking
        .order
        .iter()
        .take(positive_limit(k_prompts))
        .filter_map(|&i| {
            (ranking.scores[i] > 0.2f32).then_some((&retained[i], f64::from(ranking.scores[i])))
        })
        .collect();
    if matched.is_empty() {
        return Ok(empty("no sufficiently similar prior prompts"));
    }
    let mut outcomes = Vec::<FileOutcome>::new();
    let mut positions = BTreeMap::new();
    let mut interactions = conn.prepare("SELECT target_path,weight,session_id FROM cr_interactions WHERE context_id=? AND target_path IS NOT NULL")?;
    for (prompt, similarity) in &matched {
        let mut seen = BTreeSet::new();
        let rows = interactions.query_map(params![prompt.id], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, Option<f64>>(1)?,
                row.get::<_, i64>(2)?,
            ))
        })?;
        for row in rows {
            let (path, weight, session) = row?;
            if path.is_empty() || !seen.insert(path.clone()) {
                continue;
            }
            let index = *positions.entry(path.clone()).or_insert_with(|| {
                let index = outcomes.len();
                outcomes.push(FileOutcome {
                    path,
                    score: 0.0,
                    hits: 0,
                    sessions: BTreeSet::new(),
                });
                index
            });
            let file = &mut outcomes[index];
            let weight = weight.filter(|v| *v != 0.0).unwrap_or(1.0);
            file.score += similarity * weight;
            file.hits += 1;
            file.sessions.insert(session);
        }
    }
    if let Some(root) = root {
        let paths = crate::project(root)?;
        let context = ken_core::project::DiscoveryContext::from_process()
            .map_err(|e| HistoryError::Invalid(e.to_string()))?;
        outcomes.retain(|file| {
            paths
                .resolve_inside(Path::new(&file.path), &context)
                .is_ok_and(|path| path.exists())
        });
    }
    // Stable sorting retains first encounter order for equal scores, including
    // the numerical provider's explicit ordering of tied prompts.
    outcomes.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    let files: Vec<_> = outcomes.iter().take(positive_limit(limit)).map(|file| json!({"path":file.path,"behavioral_score":rounded(file.score,3),"times_touched":file.hits,"sessions":file.sessions.len()})).collect();
    let prompts: Vec<_> = matched.iter().take(5).map(|(prompt, similarity)| json!({"text":prompt.content.as_deref().unwrap_or("").chars().take(160).collect::<String>(),"similarity":rounded(*similarity,3)})).collect();
    Ok(json!({"ok":true,"query":query,"matched_prompts":prompts,"files":files}))
}
