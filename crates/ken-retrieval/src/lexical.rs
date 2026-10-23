//! Fielded lexical scoring and snapshot-local SQL owner selection.
use crate::{
    Result, RetrievalError,
    embedding_store::retrieval_snapshot,
    query::{Candidate, SearchRequest, Signals},
    storage::load_passage_map,
    vocabulary::code_tokens_python,
};
use rusqlite::{Connection, params_from_iter};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
pub const FIELDS: [&str; 5] = ["identity", "signature", "documentation", "body", "path"];
#[derive(Clone, Debug)]
pub struct Posting {
    pub passage_id: i64,
    pub field: String,
    pub term: String,
    pub tf: f64,
    pub length: f64,
}
impl From<(i64, String, String, f64, f64)> for Posting {
    fn from((passage_id, field, term, tf, length): (i64, String, String, f64, f64)) -> Self {
        Self {
            passage_id,
            field,
            term,
            tf,
            length,
        }
    }
}
pub fn bm25f_score(
    frequencies: &BTreeMap<String, f64>,
    lengths: &BTreeMap<String, f64>,
    averages: &BTreeMap<String, f64>,
    document_frequency: i64,
    documents: i64,
    k1: f64,
    weights: Option<&BTreeMap<String, f64>>,
) -> Result<f64> {
    if documents == 0 || frequencies.is_empty() {
        return Ok(0.);
    }
    if !(0..=documents).contains(&document_frequency) {
        return Err(RetrievalError::Invalid("invalid document frequency".into()));
    }
    let mut tf = 0.;
    for (name, frequency) in frequencies {
        let b = if matches!(name.as_str(), "body" | "documentation") {
            0.75
        } else {
            0.
        };
        let average = averages.get(name).copied().unwrap_or(0.);
        let norm = if average != 0. {
            1. - b + b * lengths.get(name).copied().unwrap_or(0.) / average
        } else {
            1.
        };
        if norm == 0. {
            return Err(RetrievalError::Invalid("float division by zero".into()));
        }
        tf += weights.and_then(|w| w.get(name)).copied().unwrap_or(1.) * frequency / norm;
    }
    if tf <= 0. {
        return Ok(0.);
    }
    let idf = ((documents as f64 - document_frequency as f64 + 0.5)
        / (document_frequency as f64 + 0.5))
        .ln_1p();
    let denominator = k1 + tf;
    if denominator == 0. {
        return Err(RetrievalError::Invalid("float division by zero".into()));
    }
    Ok(idf * (k1 + 1.) * tf / denominator)
}
pub fn score_postings(
    rows: &[Posting],
    documents: i64,
    averages: &BTreeMap<String, f64>,
) -> Result<BTreeMap<i64, Signals>> {
    if rows.is_empty() {
        return Ok(BTreeMap::new());
    }
    let ids: Vec<_> = rows
        .iter()
        .map(|r| r.passage_id)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    let positions: HashMap<_, _> = ids.iter().enumerate().map(|(i, &id)| (id, i)).collect();
    let mut terms = HashMap::new();
    for row in rows {
        let next = terms.len();
        terms.entry(row.term.as_str()).or_insert(next);
    }
    let mut combined = vec![vec![0.; terms.len()]; ids.len()];
    let mut normalized = Vec::with_capacity(rows.len());
    for row in rows {
        let field = FIELDS.iter().position(|&f| f == row.field).ok_or_else(|| {
            RetrievalError::Invalid(format!("unknown lexical field {}", row.field))
        })?;
        let average = averages.get(&row.field).copied().unwrap_or(0.);
        let norm = if matches!(field, 2 | 3) && average > 0. {
            0.25 + 0.75 * row.length / average
        } else {
            1.
        };
        let tf = row.tf / norm;
        let local = positions[&row.passage_id];
        let term = terms[row.term.as_str()];
        combined[local][term] += tf;
        normalized.push((local, field, term, tf));
    }
    let idf: Vec<_> = (0..terms.len())
        .map(|term| {
            let df = combined.iter().filter(|row| row[term] != 0.).count() as f64;
            ((documents as f64 - df + 0.5) / (df + 0.5)).ln_1p()
        })
        .collect();
    let mut individual = vec![[0.; 5]; ids.len()];
    for (local, field, term, tf) in normalized {
        individual[local][field] += idf[term] * 2.2 * tf / (1.2 + tf)
    }
    Ok(ids
        .into_iter()
        .enumerate()
        .map(|(i, id)| {
            let total = combined[i]
                .iter()
                .enumerate()
                .map(|(term, &tf)| idf[term] * 2.2 * tf / (1.2 + tf))
                .sum();
            let mut signals = Signals::from([("bm25f".into(), total)]);
            for (j, field) in FIELDS.iter().enumerate() {
                signals.insert(format!("bm25_{field}"), individual[i][j]);
            }
            (id, signals)
        })
        .collect())
}
pub fn lexical_candidates(
    conn: &Connection,
    request: &SearchRequest,
    limit: isize,
) -> Result<Vec<Candidate>> {
    let snapshot = retrieval_snapshot(conn)?;
    let mut seen = HashSet::new();
    let terms: Vec<_> = code_tokens_python(request.query())
        .into_iter()
        .filter(|term| seen.insert(term.clone()))
        .take(128)
        .collect();
    if terms.is_empty() {
        return Ok(Vec::new());
    }
    let placeholders = std::iter::repeat_n("?", terms.len())
        .collect::<Vec<_>>()
        .join(",");
    let sql = format!(
        "SELECT t.passage_id,t.field,t.term,t.tf,l.length,p.file_id,p.symbol_id FROM ci_passage_terms t JOIN ci_passages p ON p.id=t.passage_id JOIN ci_passage_lengths l ON l.passage_id=t.passage_id AND l.field=t.field WHERE t.term IN ({placeholders})"
    );
    let mut query = conn.prepare(&sql)?;
    let mut postings = Vec::new();
    let mut owners = HashMap::new();
    for row in query.query_map(params_from_iter(&terms), |r| {
        Ok((
            Posting {
                passage_id: r.get(0)?,
                field: r.get(1)?,
                term: r.get(2)?,
                tf: r.get(3)?,
                length: r.get(4)?,
            },
            r.get::<_, i64>(5)?,
            r.get::<_, Option<i64>>(6)?,
        ))
    })? {
        let (posting, file, symbol) = row?;
        owners.insert(posting.passage_id, (file, symbol));
        postings.push(posting);
    }
    if postings.is_empty() {
        return Ok(Vec::new());
    }
    let documents = conn.query_row("SELECT COUNT(*) FROM ci_passages", [], |r| {
        r.get::<_, i64>(0)
    })?;
    let averages = conn
        .prepare("SELECT field,AVG(length) FROM ci_passage_lengths GROUP BY field")?
        .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, f64>(1)?)))?
        .collect::<rusqlite::Result<BTreeMap<_, _>>>()?;
    let scores = score_postings(&postings, documents, &averages)?;
    let mut ranked: Vec<_> = scores.keys().copied().collect();
    ranked.sort_by(|a, b| {
        scores[b]["bm25f"]
            .partial_cmp(&scores[a]["bm25f"])
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.cmp(b))
    });
    let mut grouped: Vec<Vec<i64>> = Vec::new();
    let mut groups = HashMap::new();
    for id in ranked {
        let next = groups.len();
        let index = *groups.entry(owners[&id]).or_insert_with(|| {
            grouped.push(Vec::new());
            next
        });
        grouped[index].push(id)
    }
    grouped.truncate(limit.max(1) as usize);
    let ids: Vec<_> = grouped
        .iter()
        .flat_map(|g| g.iter().take(4).copied())
        .collect();
    let passages: HashMap<_, _> = load_passage_map(conn, Some(&ids))?.into_iter().collect();
    let mut out = Vec::new();
    for group in grouped {
        let owned: Vec<_> = group
            .iter()
            .take(4)
            .map(|id| passages[id].clone())
            .collect();
        let mut signals = Signals::new();
        for id in &group {
            for (name, &score) in &scores[id] {
                signals
                    .entry(name.clone())
                    .and_modify(|n| *n = n.max(score))
                    .or_insert(score);
            }
        }
        out.push(Candidate {
            entity: owned[0].entity.clone(),
            passages: owned,
            signals,
            owned_regions: Vec::new(),
        });
    }
    snapshot.finish()?;
    Ok(out)
}
