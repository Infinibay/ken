//! Select canonical owners from one pinned source generation.
use crate::{
    EntityKey, Passage, Result,
    embedding_store::retrieval_snapshot,
    intent::interpret,
    query::{Candidate, SearchRequest, Signals, merge_spans},
    source_locator::symbol_locator,
    storage::load_passage_map,
};
use ken_text::unicode::casefold;
use rusqlite::{Connection, params_from_iter};
use std::collections::{HashMap, HashSet};
type NamedOwner = (String, String, Option<String>);
struct NamedSymbol {
    name: String,
    kind: String,
    qualname: Option<String>,
    path: String,
}
fn named_symbols(conn: &Connection, request: &SearchRequest) -> Result<HashSet<NamedOwner>> {
    let intent = interpret(request);
    if intent.identifiers.is_empty() {
        return Ok(HashSet::new());
    }
    let placeholders = std::iter::repeat_n("?", intent.identifiers.len())
        .collect::<Vec<_>>()
        .join(",");
    let sql = format!(
        "SELECT s.name,s.kind,s.qualname,f.path FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id WHERE s.name COLLATE NOCASE IN ({placeholders}) OR s.qualname COLLATE NOCASE IN ({placeholders}) ORDER BY f.path,s.line_start,s.id"
    );
    let mut query = conn.prepare(&sql)?;
    let rows = query
        .query_map(
            params_from_iter(intent.identifiers.iter().chain(&intent.identifiers)),
            |r| {
                Ok(NamedSymbol {
                    name: r.get(0)?,
                    kind: r.get(1)?,
                    qualname: r.get(2)?,
                    path: r.get(3)?,
                })
            },
        )?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    let rows: Vec<_> = rows
        .iter()
        .filter(|r| intent.kind.as_ref().is_none_or(|kind| kind == &r.kind))
        .collect();
    let mut matching = HashSet::new();
    for identifier in intent.identifiers {
        let exact_case = rows
            .iter()
            .any(|r| r.name == identifier || r.qualname.as_deref() == Some(&identifier));
        let folded = casefold(&identifier);
        for row in &rows {
            let selected = if exact_case {
                row.name == identifier || row.qualname.as_deref() == Some(&identifier)
            } else {
                casefold(&row.name) == folded
                    || row.qualname.as_ref().is_some_and(|q| casefold(q) == folded)
            };
            if selected {
                matching.insert((row.path.clone(), row.kind.clone(), row.qualname.clone()));
            }
        }
    }
    Ok(matching)
}
pub(crate) fn exact_from_passages(
    conn: &Connection,
    passages: &[(i64, Passage)],
    request: &SearchRequest,
) -> Result<Vec<Candidate>> {
    let matching = if let Some(locator) = symbol_locator(request.query()) {
        passages
            .iter()
            .filter(|(_, p)| locator.matches(&p.entity))
            .map(|(_, p)| {
                (
                    p.entity.path.clone(),
                    p.entity.kind.clone(),
                    p.entity.qualname.clone(),
                )
            })
            .collect()
    } else {
        named_symbols(conn, request)?
    };
    let mut groups: HashMap<EntityKey, usize> = HashMap::new();
    let mut result: Vec<Candidate> = Vec::new();
    for (_, passage) in passages {
        let entity = &passage.entity;
        if !matching.contains(&(
            entity.path.clone(),
            entity.kind.clone(),
            entity.qualname.clone(),
        )) {
            continue;
        }
        let index = if let Some(&index) = groups.get(entity) {
            index
        } else {
            let index = result.len();
            groups.insert(entity.clone(), index);
            result.push(Candidate {
                entity: entity.clone(),
                passages: Vec::new(),
                signals: Signals::from([("exact".into(), 1.)]),
                owned_regions: Vec::new(),
            });
            index
        };
        result[index].passages.push(passage.clone());
    }
    for candidate in &mut result {
        candidate.owned_regions = merge_spans(
            &candidate
                .passages
                .iter()
                .map(|p| p.span)
                .collect::<Vec<_>>(),
        );
    }
    Ok(result)
}
/// Literal identity needs current source ownership, never an embedding runtime.
pub fn exact_candidates(conn: &Connection, request: &SearchRequest) -> Result<Vec<Candidate>> {
    let snapshot = retrieval_snapshot(conn)?;
    let result = exact_from_passages(conn, &load_passage_map(conn, None)?, request)?;
    snapshot.finish()?;
    Ok(result)
}
