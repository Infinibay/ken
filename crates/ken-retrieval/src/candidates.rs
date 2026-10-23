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
use std::{
    borrow::Borrow,
    collections::{HashMap, HashSet},
    sync::Arc,
};
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
pub(crate) fn exact_from_passages<P: Borrow<Passage>>(
    conn: &Connection,
    passages: &[(i64, P)],
    request: &SearchRequest,
) -> Result<Vec<Candidate>> {
    let matching = if let Some(locator) = symbol_locator(request.query()) {
        passages
            .iter()
            .filter(|(_, p)| locator.matches(&p.borrow().entity))
            .map(|(_, p)| {
                let p = p.borrow();
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
        let passage = passage.borrow();
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

use crate::{
    RetrievalError, Span,
    dense::DenseView,
    description::{OwnerDescription, describe_owner},
    embedding_store::load_vectors,
    lexical::lexical_candidates,
    projections::source_policy,
    proposals::max_signals,
    query_encoder::QueryEncoders,
};
use ken_models::{LegacyRuntimeIdentity, RetrievalProfile};
use rusqlite::OptionalExtension;
use std::rc::Rc;

fn group_passages(passages: Vec<(i64, Passage)>) -> Vec<(EntityKey, Vec<Passage>)> {
    let mut positions = HashMap::new();
    let mut owners: Vec<(EntityKey, Vec<Passage>)> = Vec::new();
    for (_, passage) in passages {
        let index = if let Some(&index) = positions.get(&passage.entity) {
            index
        } else {
            let index = owners.len();
            positions.insert(passage.entity.clone(), index);
            owners.push((passage.entity.clone(), Vec::new()));
            index
        };
        owners[index].1.push(passage);
    }
    owners
}
pub fn owner_passages(conn: &Connection) -> Result<Vec<(EntityKey, Vec<Passage>)>> {
    let snapshot = retrieval_snapshot(conn)?;
    let owners = group_passages(load_passage_map(conn, None)?);
    snapshot.finish()?;
    Ok(owners)
}
pub fn owner_descriptions(
    conn: &Connection,
    candidates: &[Candidate],
) -> Result<Vec<(EntityKey, OwnerDescription)>> {
    let snapshot = retrieval_snapshot(conn)?;
    let owners: HashMap<_, _> = group_passages(load_passage_map(conn, None)?)
        .into_iter()
        .collect();
    if candidates
        .iter()
        .any(|c| !owners.contains_key(&c.entity) || c.passages.is_empty())
    {
        return Err(RetrievalError::Version(
            "owner changed before ranking; retry retrieval".into(),
        ));
    }
    let mut result = Vec::new();
    let mut seen = HashSet::new();
    for candidate in candidates {
        if seen.insert(&candidate.entity) {
            result.push((
                candidate.entity.clone(),
                describe_owner(&owners[&candidate.entity])?,
            ));
        }
    }
    let descriptions: HashMap<_, _> = result.iter().map(|(entity, d)| (entity, d)).collect();
    if candidates
        .iter()
        .any(|c| descriptions[&c.entity].source_hash != c.passages[0].source_hash)
    {
        return Err(RetrievalError::Version(
            "source changed before owner ranking; retry retrieval".into(),
        ));
    }
    snapshot.finish()?;
    Ok(result)
}
fn validate_source_policy(
    conn: &Connection,
    profile: &RetrievalProfile,
    legacy: &LegacyRuntimeIdentity,
) -> Result<()> {
    let version: Option<String> = conn
        .query_row(
            "SELECT value FROM meta WHERE key='retrieval_representation_version'",
            [],
            |r| r.get(0),
        )
        .optional()?;
    if version.as_deref() != Some(&profile.representation_version.to_string()) {
        return Err(RetrievalError::Version(
            "retrieval representation changed; reindex the project".into(),
        ));
    }
    let policy = source_policy(profile, legacy)?;
    let mut query = conn.prepare(
        "SELECT DISTINCT extractor_version,tokenizer_version,max_tokens FROM ci_retrieval_files",
    )?;
    let rows = query.query_map([], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, i64>(2)?,
        ))
    })?;
    for row in rows {
        let valid = row.is_ok_and(|(extractor, tokenizer, max_tokens)| {
            extractor == crate::EXTRACTOR_VERSION as i64
                && tokenizer == policy.tokenizer_version
                && max_tokens >= 0
                && max_tokens as usize == policy.max_tokens
        });
        if !valid {
            return Err(RetrievalError::Version(
                "source passage policy changed; reindex the project".into(),
            ));
        }
    }
    Ok(())
}
fn merge_channels(channels: Vec<Vec<Candidate>>, profile: &RetrievalProfile) -> Vec<Candidate> {
    let mut positions = HashMap::new();
    let mut result: Vec<Candidate> = Vec::new();
    for channel in channels {
        for (rank, candidate) in channel.into_iter().enumerate() {
            let index = if let Some(&index) = positions.get(&candidate.entity) {
                index
            } else {
                let index = result.len();
                positions.insert(candidate.entity.clone(), index);
                result.push(Candidate {
                    entity: candidate.entity.clone(),
                    passages: Vec::new(),
                    signals: Signals::from([("rrf".into(), 0.)]),
                    owned_regions: Vec::new(),
                });
                index
            };
            let combined = &mut result[index];
            max_signals(&mut combined.signals, &candidate.signals);
            *combined.signals.get_mut("rrf").expect("union RRF") +=
                1. / (profile.rrf_k as f64 + rank as f64 + 1.);
            let mut spans: HashMap<_, _> = combined
                .passages
                .iter()
                .enumerate()
                .map(|(i, p)| ((p.span.start_line, p.span.end_line), i))
                .collect();
            for passage in candidate.passages {
                let span = (passage.span.start_line, passage.span.end_line);
                if let Some(&index) = spans.get(&span) {
                    combined.passages[index].signals.extend(passage.signals);
                } else {
                    spans.insert(span, combined.passages.len());
                    combined.passages.push(passage);
                }
            }
        }
    }
    result.sort_by(|a, b| {
        b.signals
            .get("exact")
            .copied()
            .unwrap_or(0.)
            .total_cmp(&a.signals.get("exact").copied().unwrap_or(0.))
            .then_with(|| b.signals["rrf"].total_cmp(&a.signals["rrf"]))
            .then(a.entity.path.cmp(&b.entity.path))
            .then_with(|| {
                a.passages
                    .iter()
                    .map(|p| p.span.start_line)
                    .min()
                    .cmp(&b.passages.iter().map(|p| p.span.start_line).min())
            })
    });
    result.truncate(profile.candidate_limit);
    result
}
pub fn retrieve(
    conn: &Connection,
    request: &SearchRequest,
    profile: &RetrievalProfile,
    legacy: &LegacyRuntimeIdentity,
    encoders: &QueryEncoders,
) -> Result<Vec<Candidate>> {
    profile.validate()?;
    let snapshot = retrieval_snapshot(conn)?;
    let passages: Vec<_> = load_passage_map(conn, None)?
        .into_iter()
        .map(|(id, p)| (id, Arc::new(p)))
        .collect();
    if passages.is_empty() {
        return Err(RetrievalError::Version(
            "no source passages; reindex the project".into(),
        ));
    }
    let mut exact = exact_from_passages(conn, &passages, request)?;
    if exact.len() == 1 {
        exact[0].signals.insert("rrf".into(), 1.);
        snapshot.finish()?;
        return Ok(exact);
    }
    validate_source_policy(conn, profile, legacy)?;
    let limit = isize::try_from(profile.candidate_limit).unwrap_or(isize::MAX);
    let mut channels = vec![exact, lexical_candidates(conn, request, limit)?];
    let ids: HashSet<_> = passages.iter().map(|(id, _)| *id).collect();
    let mut original_query = None;
    for (view, encoder) in [
        ("identity", &encoders.identity),
        ("behavior", &encoders.behavior),
    ] {
        let revision = profile.vector_revision(view, legacy)?;
        let vectors = load_vectors(conn, view, &revision)?;
        if vectors.ids.iter().copied().collect::<HashSet<_>>() != ids {
            return Err(RetrievalError::Version(format!(
                "incomplete {view} vectors; reindex the retrieval profile"
            )));
        }
        let dense = DenseView::from_shared(passages.clone(), vectors)?;
        let query = if view == "behavior" && Rc::ptr_eq(&encoders.identity, &encoders.behavior) {
            original_query.take().expect("identity query first")
        } else {
            encoder.embed_query(request.query())?
        };
        channels.push(dense.search(&query, view, limit)?);
        if view == "identity" {
            original_query = Some(query);
        }
    }
    let mut result = merge_channels(channels, profile);
    let mut regions: HashMap<&EntityKey, Vec<Span>> = HashMap::new();
    for (_, passage) in &passages {
        regions
            .entry(&passage.entity)
            .or_default()
            .push(passage.span);
    }
    for candidate in &mut result {
        candidate.owned_regions = merge_spans(&regions[&candidate.entity]);
    }
    snapshot.finish()?;
    Ok(result)
}

pub type QueryExpander<'a> = dyn Fn(&ken_text::PythonText) -> Result<ken_text::PythonText> + 'a;

/// Query expansion contributes proposals; only the original query grants exact authority.
pub fn retrieve_contextual(
    conn: &Connection,
    request: &SearchRequest,
    profile: &RetrievalProfile,
    legacy: &LegacyRuntimeIdentity,
    encoders: &QueryEncoders,
    runtime: Option<&crate::contextual::ContextualRetriever>,
    expand_query: Option<&QueryExpander<'_>>,
) -> Result<(Vec<Candidate>, ken_text::PythonText)> {
    let policy = profile.contextual.as_ref().ok_or_else(|| {
        RetrievalError::Invalid("contextual retrieval requires its pinned source policy".into())
    })?;
    let mut source_profile = profile.clone();
    source_profile.candidate_limit = policy.channel_limit;
    let snapshot = retrieval_snapshot(conn)?;
    let original = retrieve(conn, request, &source_profile, legacy, encoders)?;
    if original.len() == 1 && original[0].signals.get("exact").is_some_and(|x| *x != 0.) {
        snapshot.finish()?;
        return Ok((original, request.query().clone()));
    }
    let (runtime, expand_query) = runtime.zip(expand_query).ok_or_else(|| {
        RetrievalError::Invalid(
            "contextual profile requires its pinned retriever and query preparation".into(),
        )
    })?;
    let expanded = expand_query(request.query())?;
    if expanded
        .codepoints()
        .iter()
        .all(|&c| char::from_u32(c).is_some_and(ken_text::unicode::whitespace))
    {
        return Err(RetrievalError::Invalid(
            "contextual expansion must return nonempty query text".into(),
        ));
    }
    fn without_exact(candidates: Vec<Candidate>) -> Vec<Candidate> {
        candidates
            .into_iter()
            .map(|mut c| {
                c.signals.remove("exact");
                c
            })
            .collect()
    }
    let mut runs = vec![("original".into(), original)];
    if expanded != *request.query() {
        let translated = retrieve(
            conn,
            &request.with_query(expanded.clone())?,
            &source_profile,
            legacy,
            encoders,
        )?;
        runs.push(("expanded".into(), without_exact(translated)));
    }
    let static_limit = policy.channel_limit.checked_mul(2).ok_or_else(|| {
        RetrievalError::Invalid("contextual proposal budget exceeds the native limit".into())
    })?;
    let static_proposals = crate::proposals::fuse_proposals(&runs, static_limit, profile.rrf_k)?;
    let passages = load_passage_map(conn, None)?;
    let exact = exact_from_passages(conn, &passages, request)?;
    let owners = group_passages(passages);
    let scores = runtime.score(
        request.query(),
        &expanded,
        &owners,
        snapshot.generation,
        policy,
    )?;
    let code_limit = isize::try_from(policy.channel_limit).map_err(|_| {
        RetrievalError::Invalid("contextual proposal budget exceeds the native limit".into())
    })?;
    let mut combined = crate::proposals::fuse_proposals(
        &[
            ("static".into(), without_exact(static_proposals)),
            ("code".into(), scores.propose(&owners, code_limit)?),
            ("exact".into(), exact),
        ],
        policy.broad_limit,
        profile.rrf_k,
    )?;
    scores.enrich(&mut combined)?;
    snapshot.finish()?;
    Ok((combined, expanded))
}
