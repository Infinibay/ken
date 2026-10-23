//! Coordinate source features, a pinned forest, and visible owned evidence.
use crate::{
    EntityKey, Result, RetrievalError,
    candidates::QueryExpander,
    contextual_features,
    description::OwnerDescription,
    evidence_features,
    intent::requested_piece_kind,
    matrix::Matrix,
    numeric_ranker::NumericRanker,
    query::{Candidate, CodeMatch, SearchRequest},
    ranking::rank_candidates,
    ranking_trace::{EXACT_ORDER_POLICY, MODEL_ORDER_POLICY, RankingTrace, TraceObservation},
    stemming::WordStemmer,
    vocabulary::code_tokens_python,
    word_encoder::WordEncoder,
};
use ken_models::EvidenceRanking;
use ken_text::PythonText;
use std::{
    collections::{BTreeMap, BTreeSet},
    rc::Rc,
    sync::Arc,
};
pub struct ExpansionConfig {
    pub expand_query: Option<Rc<QueryExpander<'static>>>,
    pub revision: Option<String>,
}
pub struct EvidenceReranker {
    model: Arc<NumericRanker>,
    encoder: Rc<dyn WordEncoder>,
    stemmer: Arc<dyn WordStemmer>,
    expansion: Option<(Rc<QueryExpander<'static>>, String)>,
    feature_version: usize,
}
impl EvidenceReranker {
    pub fn new(
        model: Arc<NumericRanker>,
        encoder: Rc<dyn WordEncoder>,
        stemmer: Arc<dyn WordStemmer>,
        expansion: Option<ExpansionConfig>,
    ) -> Result<Self> {
        let base = evidence_features::feature_names();
        let schemas = [
            base.clone(),
            base.iter()
                .cloned()
                .chain(contextual_features::feature_names(false))
                .collect(),
            base.into_iter()
                .chain(contextual_features::feature_names(true))
                .collect(),
        ];
        let feature_version = schemas
            .iter()
            .position(|s| s == model.features())
            .ok_or_else(|| {
                RetrievalError::Invalid(
                    "numeric model uses an incompatible source feature schema".into(),
                )
            })?
            + 1;
        let expansion = match expansion {
            None => None,
            Some(ExpansionConfig {
                expand_query: None,
                revision: None,
            }) => None,
            Some(ExpansionConfig {
                expand_query: Some(f),
                revision: Some(r),
            }) => Some((f, r)),
            _ => {
                return Err(RetrievalError::Invalid(
                    "query expansion requires its immutable revision".into(),
                ));
            }
        };
        Ok(Self {
            model,
            encoder,
            stemmer,
            expansion,
            feature_version,
        })
    }
    pub fn feature_version(&self) -> usize {
        self.feature_version
    }
    pub fn validate(&self, spec: &EvidenceRanking) -> Result<()> {
        if self.model.fingerprint()? != spec.model_revision
            || self.encoder.spec() != &spec.word_model
            || self.expansion.as_ref().map(|(_, r)| r) != spec.expansion_revision.as_ref()
            || self.feature_version != spec.feature_version
        {
            return Err(RetrievalError::Invalid(
                "owner ranking runtime does not match its pinned profile".into(),
            ));
        }
        Ok(())
    }
    pub fn prepare_query(&self, query: &PythonText) -> Result<PythonText> {
        let expanded = match &self.expansion {
            Some((f, _)) => f(query)?,
            None => query.clone(),
        };
        if expanded.clone().trimmed().codepoints().is_empty() {
            return Err(RetrievalError::Invalid(
                "query expansion must return nonempty text".into(),
            ));
        }
        Ok(expanded)
    }
    pub fn rank(
        &self,
        request: &SearchRequest,
        candidates: &[Candidate],
        descriptions: &BTreeMap<EntityKey, OwnerDescription>,
        expanded: Option<&PythonText>,
        evidence_version: usize,
        trace: Option<&mut RankingTrace>,
    ) -> Result<Vec<CodeMatch>> {
        if !(1..=3).contains(&evidence_version) {
            return Err(RetrievalError::Invalid(
                "unsupported source evidence policy".into(),
            ));
        }
        let piece_kind = requested_piece_kind(request);
        if candidates.len() == 1 && candidates[0].signals.get("exact").is_some_and(|v| *v != 0.) {
            let matches = rank_candidates(request, candidates, None, 40, "entity")?;
            if let Some(trace) = trace {
                trace.record(TraceObservation {
                    model: &self.model,
                    query: request.query(),
                    expanded: request.query(),
                    candidates,
                    matches: &matches,
                    values: None,
                    feature_version: self.feature_version,
                    evidence_version,
                    policy: EXACT_ORDER_POLICY,
                    piece_kind: Some(&piece_kind),
                })?;
            }
            return Ok(matches);
        }
        let prepared;
        let expanded = match expanded {
            Some(q) => q,
            None => {
                prepared = self.prepare_query(request.query())?;
                &prepared
            }
        };
        let features = evidence_features::evidence_features(
            request,
            candidates,
            descriptions,
            self.encoder.as_ref(),
            self.stemmer.as_ref(),
            Some(expanded),
        )?;
        let values = if self.feature_version >= 2 {
            let context =
                contextual_features::contextual_features(candidates, self.feature_version == 3)?;
            let columns = features.values.columns() + context.values.columns();
            let mut combined = Vec::with_capacity(candidates.len() * columns);
            for row in 0..candidates.len() {
                combined.extend_from_slice(
                    &features.values.values()
                        [row * features.values.columns()..(row + 1) * features.values.columns()],
                );
                combined.extend_from_slice(
                    &context.values.values()
                        [row * context.values.columns()..(row + 1) * context.values.columns()],
                );
            }
            Matrix::new(candidates.len(), columns, combined)?
        } else {
            features.values
        };
        let scores = self.model.predict(&values)?;
        let terms: BTreeSet<_> = code_tokens_python(expanded).into_iter().collect();
        let mut matches: Vec<_> = candidates
            .iter()
            .zip(scores)
            .map(|(c, score)| {
                let evidence = if evidence_version >= 2 {
                    c.passages.clone()
                } else {
                    let retrieved: BTreeMap<_, _> =
                        c.passages.iter().map(|p| (p.span, &p.signals)).collect();
                    descriptions[&c.entity]
                        .passages
                        .iter()
                        .map(|p| {
                            let mut passage = p.clone();
                            passage.signals = retrieved
                                .get(&p.span)
                                .copied()
                                .unwrap_or(&p.signals)
                                .clone();
                            let body: BTreeSet<_> =
                                code_tokens_python(&p.fields.body).into_iter().collect();
                            passage.signals.insert(
                                "joint_evidence".into(),
                                terms.intersection(&body).count() as f64
                                    / terms.len().max(1) as f64,
                            );
                            passage
                        })
                        .collect()
                };
                let mut signals = c.signals.clone();
                signals.insert("evidence_relevance".into(), score);
                CodeMatch {
                    entity: c.entity.clone(),
                    score,
                    evidence,
                    source_hash: c.passages[0].source_hash.clone(),
                    signals,
                    owned_regions: c.owned_regions.clone(),
                }
            })
            .collect();
        matches.sort_by(|a, b| {
            b.signals
                .get("exact")
                .unwrap_or(&0.)
                .partial_cmp(a.signals.get("exact").unwrap_or(&0.))
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| {
                    b.score
                        .partial_cmp(&a.score)
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
        });
        if let Some(trace) = trace {
            trace.record(TraceObservation {
                model: &self.model,
                query: request.query(),
                expanded,
                candidates,
                matches: &matches,
                values: Some(&values),
                feature_version: self.feature_version,
                evidence_version,
                policy: MODEL_ORDER_POLICY,
                piece_kind: Some(&piece_kind),
            })?;
        }
        Ok(matches)
    }
}
