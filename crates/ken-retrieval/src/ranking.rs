//! Judge canonical owners or their distinct owned evidence without changing proposals.
use crate::{
    EntityKey, Passage, Result, RetrievalError,
    intent::interpret,
    query::{Candidate, CodeMatch, SearchRequest},
};
use ken_text::{PythonText, unicode::whitespace};
use std::{
    cmp::Ordering,
    collections::{BTreeMap, HashMap},
    sync::Arc,
};

pub trait RelevanceJudge {
    fn score(
        &self,
        query: &PythonText,
        documents: &[PythonText],
        purpose: &str,
    ) -> Result<Vec<f64>>;
}
/// Connects owner/evidence selection to the previously accepted native joint model.
pub struct JointModelJudge(pub Arc<ken_models::RelevanceJudge>);
impl RelevanceJudge for JointModelJudge {
    fn score(
        &self,
        query: &PythonText,
        documents: &[PythonText],
        purpose: &str,
    ) -> Result<Vec<f64>> {
        let scalar = |text: &PythonText| {
            text.to_utf8().ok_or_else(|| {
                RetrievalError::Invalid(
                    "non-scalar Unicode cannot be passed to the joint model".into(),
                )
            })
        };
        let query = scalar(query)?;
        let documents = documents.iter().map(scalar).collect::<Result<Vec<_>>>()?;
        Ok(self
            .0
            .score(
                &query,
                &documents.iter().map(String::as_str).collect::<Vec<_>>(),
                purpose,
            )?
            .into_iter()
            .map(f64::from)
            .collect())
    }
}
fn join(parts: &[PythonText], separator: &str) -> PythonText {
    let mut points = Vec::new();
    for (index, part) in parts.iter().enumerate() {
        if index > 0 {
            points.extend(separator.chars().map(u32::from));
        }
        points.extend_from_slice(part.codepoints());
    }
    PythonText::from_codepoints(points).expect("owned source codepoints")
}
fn nonblank(text: &PythonText) -> bool {
    text.codepoints()
        .iter()
        .any(|&c| !char::from_u32(c).is_some_and(whitespace))
}
fn executable(passage: &Passage) -> bool {
    passage
        .implementation_start_line
        .is_none_or(|start| passage.span.end_line >= start)
}
fn descending(a: f64, b: f64) -> Ordering {
    b.partial_cmp(&a).unwrap_or(Ordering::Equal)
}
pub fn candidate_document(candidate: &Candidate, purpose: &str) -> Result<PythonText> {
    let first = candidate.passages.first().ok_or_else(|| {
        RetrievalError::Invalid("candidate document requires owned source evidence".into())
    })?;
    let mut ordered: Vec<_> = candidate.passages.iter().collect();
    ordered.sort_by(|a, b| {
        executable(b)
            .cmp(&executable(a))
            .then_with(|| {
                descending(
                    *a.signals.get("cosine_behavior").unwrap_or(&-1.),
                    *b.signals.get("cosine_behavior").unwrap_or(&-1.),
                )
            })
            .then(a.span.start_line.cmp(&b.span.start_line))
    });
    let mut bodies = Vec::new();
    for passage in ordered {
        let body = if matches!(purpose, "implementation" | "tests" | "usage") {
            if let Some(start) = passage.implementation_start_line {
                let lines: Vec<_> = passage
                    .fields
                    .body
                    .codepoints()
                    .split(|c| *c == 10)
                    .skip(start.saturating_sub(passage.span.start_line))
                    .map(|points| {
                        PythonText::from_codepoints(points.to_vec()).expect("body codepoints")
                    })
                    .collect();
                join(&lines, "\n")
            } else {
                passage.fields.body.clone()
            }
        } else {
            passage.fields.body.clone()
        };
        if nonblank(&body) && !bodies.contains(&body) {
            bodies.push(body);
        }
        if bodies.len() == 4 {
            break;
        }
    }
    let documentation = if matches!(purpose, "identity" | "documentation") {
        PythonText::from_codepoints(
            first
                .fields
                .documentation
                .codepoints()
                .iter()
                .copied()
                .take(600)
                .collect(),
        )
        .expect("documentation codepoints")
    } else {
        "".into()
    };
    let source = if bodies.is_empty() {
        "<no owned executable source>".into()
    } else {
        join(&bodies, "\n\n")
    };
    Ok(join(
        &[
            candidate.entity.path.clone().into(),
            first.role.clone().into(),
            first.fields.identity.clone(),
            first.fields.signature.clone(),
            join(&["Source:".into(), source], "\n"),
            join(&["Documentation:".into(), documentation], "\n"),
        ],
        "\n",
    ))
}
fn code_match(candidate: &Candidate, score: f64) -> CodeMatch {
    CodeMatch {
        entity: candidate.entity.clone(),
        score,
        evidence: candidate.passages.clone(),
        source_hash: candidate.passages[0].source_hash.clone(),
        signals: candidate.signals.clone(),
        owned_regions: candidate.owned_regions.clone(),
    }
}
fn ordered_matches(matches: &mut [CodeMatch]) {
    matches.sort_by(|a, b| {
        descending(
            *a.signals.get("exact").unwrap_or(&0.),
            *b.signals.get("exact").unwrap_or(&0.),
        )
        .then_with(|| descending(a.score, b.score))
        .then(a.entity.path.cmp(&b.entity.path))
        .then(
            a.evidence[0]
                .span
                .start_line
                .cmp(&b.evidence[0].span.start_line),
        )
    });
}
fn judged_scores(
    judge: &dyn RelevanceJudge,
    request: &SearchRequest,
    documents: &[PythonText],
    purpose: &str,
    unit: &str,
) -> Result<Vec<f64>> {
    let scores = judge.score(request.query(), documents, purpose)?;
    if scores.len() != documents.len() || scores.iter().any(|x| !x.is_finite()) {
        return Err(RetrievalError::Invalid(format!(
            "joint ranker must return one finite score per {unit}"
        )));
    }
    Ok(scores)
}
pub fn rank_candidates(
    request: &SearchRequest,
    candidates: &[Candidate],
    judge: Option<&dyn RelevanceJudge>,
    rerank_limit: isize,
    rank_unit: &str,
) -> Result<Vec<CodeMatch>> {
    if candidates.iter().any(|c| c.passages.is_empty()) {
        return Err(RetrievalError::Invalid(
            "ranking requires owned source evidence".into(),
        ));
    }
    let scores: HashMap<_, _> = candidates
        .iter()
        .map(|c| (&c.entity, *c.signals.get("rrf").unwrap_or(&0.)))
        .collect();
    let mut ordered: Vec<_> = candidates.iter().collect();
    ordered.sort_by(|a, b| {
        descending(
            *a.signals.get("exact").unwrap_or(&0.),
            *b.signals.get("exact").unwrap_or(&0.),
        )
        .then_with(|| descending(scores[&a.entity], scores[&b.entity]))
        .then(a.entity.path.cmp(&b.entity.path))
        .then_with(|| {
            a.passages
                .iter()
                .map(|p| p.span.start_line)
                .min()
                .cmp(&b.passages.iter().map(|p| p.span.start_line).min())
        })
    });
    if judge.is_none()
        || (ordered.len() == 1 && ordered[0].signals.get("exact").is_some_and(|x| *x != 0.))
    {
        return Ok(ordered
            .into_iter()
            .map(|c| code_match(c, scores[&c.entity]))
            .collect());
    }
    let judge = judge.expect("non-optional after deterministic bypass");
    let length = if rerank_limit < 0 {
        ordered.len().saturating_sub(rerank_limit.unsigned_abs())
    } else {
        ordered.len().min(rerank_limit as usize)
    };
    ordered.truncate(length);
    let intent = interpret(request);
    let purpose = if intent.identity {
        "identity"
    } else {
        intent.purpose.as_str()
    };
    if rank_unit == "passage" {
        return rank_passages(request, &ordered, judge, purpose);
    }
    if rank_unit != "entity" {
        return Err(RetrievalError::Invalid("unknown joint ranking unit".into()));
    }
    let documents = ordered
        .iter()
        .map(|c| candidate_document(c, purpose))
        .collect::<Result<Vec<_>>>()?;
    let scores = judged_scores(judge, request, &documents, purpose, "candidate")?;
    let mut matches: Vec<_> = ordered
        .into_iter()
        .zip(scores)
        .map(|(candidate, score)| {
            let mut item = code_match(candidate, score);
            item.signals.insert("joint_relevance".into(), score);
            item
        })
        .collect();
    ordered_matches(&mut matches);
    Ok(matches)
}
fn rank_passages(
    request: &SearchRequest,
    candidates: &[&Candidate],
    judge: &dyn RelevanceJudge,
    purpose: &str,
) -> Result<Vec<CodeMatch>> {
    let mut units: Vec<(&Candidate, Passage)> = Vec::new();
    for &candidate in candidates {
        let mut positions = BTreeMap::new();
        let mut passages = Vec::new();
        for passage in &candidate.passages {
            if let Some(&index) = positions.get(&passage.span) {
                passages[index] = passage.clone();
            } else {
                positions.insert(passage.span, passages.len());
                passages.push(passage.clone());
            }
        }
        if !matches!(purpose, "identity" | "documentation") {
            let executable: Vec<_> = passages.iter().filter(|p| executable(p)).cloned().collect();
            if executable.is_empty() {
                passages.truncate(1);
            } else {
                passages = executable;
            }
        }
        units.extend(passages.into_iter().map(|p| (candidate, p)));
    }
    let documents = units
        .iter()
        .map(|(candidate, passage)| {
            candidate_document(
                &Candidate {
                    entity: candidate.entity.clone(),
                    passages: vec![passage.clone()],
                    signals: candidate.signals.clone(),
                    owned_regions: Vec::new(),
                },
                purpose,
            )
        })
        .collect::<Result<Vec<_>>>()?;
    let scores = judged_scores(judge, request, &documents, purpose, "evidence unit")?;
    let mut grouped: HashMap<&EntityKey, Vec<Passage>> = HashMap::new();
    for ((candidate, mut passage), score) in units.into_iter().zip(scores) {
        passage.signals.insert("joint_evidence".into(), score);
        grouped.entry(&candidate.entity).or_default().push(passage);
    }
    let mut matches = Vec::new();
    for &candidate in candidates {
        let evidence = &grouped[&candidate.entity];
        let score = evidence
            .iter()
            .map(|p| p.signals["joint_evidence"])
            .fold(f64::NEG_INFINITY, f64::max);
        let mut item = code_match(candidate, score);
        item.source_hash = evidence[0].source_hash.clone();
        item.evidence = evidence.clone();
        item.signals.extend([
            ("joint_relevance".into(), score),
            ("joint_units".into(), evidence.len() as f64),
        ]);
        matches.push(item);
    }
    ordered_matches(&mut matches);
    Ok(matches)
}
