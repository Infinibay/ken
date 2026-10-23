//! Contextual measurements belong to a complete immutable source generation.
use crate::{
    EntityKey, Passage, Result, RetrievalError,
    dense_math::DenseMath,
    model::evidence_matches,
    normalized_matrix::NormalizedMatrix,
    query::{Candidate, merge_spans},
    query_encoder::QueryEncoder,
    source_views::SourceViewSnapshot,
};
use ken_models::{ContextualRetrieval, EncoderSpec};
use ken_text::PythonText;
use std::{
    collections::{BTreeMap, BTreeSet},
    rc::Rc,
    sync::Arc,
};

#[derive(Debug)]
pub struct OwnerVectorSnapshot {
    model: EncoderSpec,
    generation: i64,
    owners: Vec<EntityKey>,
    hashes: Vec<String>,
    matrix: NormalizedMatrix,
    projection_version: usize,
}
pub(crate) fn consistent_versions(owners: &[EntityKey], hashes: &[String]) -> bool {
    let mut versions = BTreeMap::new();
    owners.iter().zip(hashes).all(|(owner, hash)| {
        !hash.is_empty() && versions.entry(&owner.path).or_insert(hash) == &hash
    })
}
impl OwnerVectorSnapshot {
    pub fn new(
        model: EncoderSpec,
        generation: i64,
        owners: Vec<EntityKey>,
        hashes: Vec<String>,
        matrix: Vec<Vec<f32>>,
        projection_version: usize,
    ) -> Result<Self> {
        if owners.iter().collect::<BTreeSet<_>>().len() != owners.len()
            || hashes.len() != owners.len()
        {
            return Err(RetrievalError::Invalid(
                "contextual vectors require unique owners and matching source hashes".into(),
            ));
        }
        if generation < 0 || projection_version != 1 {
            return Err(RetrievalError::Invalid(
                "invalid contextual source generation or projection".into(),
            ));
        }
        if !consistent_versions(&owners, &hashes) {
            return Err(RetrievalError::Invalid(
                "contextual owners contain mixed source versions".into(),
            ));
        }
        let message = "contextual source vectors must be finite and normalized";
        let matrix = NormalizedMatrix::new(matrix, message, message)?;
        if matrix.rows() != owners.len() {
            return Err(RetrievalError::Invalid(message.into()));
        }
        Ok(Self {
            model,
            generation,
            owners,
            hashes,
            matrix,
            projection_version,
        })
    }
}
pub struct ContextualRetriever {
    encoder: Rc<dyn QueryEncoder>,
    encoder_spec: EncoderSpec,
    source: Arc<OwnerVectorSnapshot>,
    views: Option<Arc<SourceViewSnapshot>>,
}
impl ContextualRetriever {
    pub fn new(
        encoder: Rc<dyn QueryEncoder>,
        encoder_spec: EncoderSpec,
        vectors: OwnerVectorSnapshot,
        source_views: Option<SourceViewSnapshot>,
    ) -> Result<Self> {
        if encoder_spec != vectors.model {
            return Err(RetrievalError::Invalid(
                "contextual encoder does not match its pinned source vectors".into(),
            ));
        }
        if source_views.as_ref().is_some_and(|v| {
            v.query_model != vectors.model
                || v.generation != vectors.generation
                || v.owners != vectors.owners
                || v.hashes != vectors.hashes
                || v.matrix.width() != vectors.matrix.width()
        }) {
            return Err(RetrievalError::Invalid(
                "source views must match the complete contextual owner source".into(),
            ));
        }
        Ok(Self {
            encoder,
            encoder_spec,
            source: Arc::new(vectors),
            views: source_views.map(Arc::new),
        })
    }
    pub fn score(
        &self,
        query: &PythonText,
        expanded: &PythonText,
        owners: &[(EntityKey, Vec<Passage>)],
        generation: i64,
        policy: &ContextualRetrieval,
    ) -> Result<ContextualScores> {
        if policy.model != self.encoder_spec
            || policy.projection_version != self.source.projection_version
        {
            return Err(RetrievalError::Invalid(
                "contextual runtime does not match its pinned profile".into(),
            ));
        }
        if policy.view_model.as_ref() != self.views.as_ref().map(|v| &v.model) {
            return Err(RetrievalError::Invalid(
                "source view runtime does not match its pinned profile".into(),
            ));
        }
        if generation != self.source.generation {
            return Err(RetrievalError::Version(
                "contextual source generation changed; reindex owner vectors".into(),
            ));
        }
        let owners: BTreeMap<_, _> = owners
            .iter()
            .map(|(key, passages)| (key, passages))
            .collect();
        if owners.keys().copied().collect::<BTreeSet<_>>() != self.source.owners.iter().collect() {
            return Err(RetrievalError::Version(
                "contextual index must cover all source owners; reindex owner vectors".into(),
            ));
        }
        for (entity, hash) in self.source.owners.iter().zip(&self.source.hashes) {
            let passages = owners[entity];
            if !evidence_matches(entity, hash, passages) {
                return Err(RetrievalError::Version(
                    "contextual owner source changed; reindex owner vectors".into(),
                ));
            }
        }
        let encode = |text: &PythonText| -> Result<Arc<Vec<f32>>> {
            let mut vector = self.encoder.embed_query(text)?;
            let norm = DenseMath::platform()?.norm(&vector)?;
            if vector.len() != self.source.matrix.width()
                || vector.iter().any(|x| !x.is_finite())
                || !norm.is_finite()
                || norm <= 1e-9
            {
                return Err(RetrievalError::Invalid(
                    "contextual query must have a finite, positive vector of the indexed dimension"
                        .into(),
                ));
            }
            for x in &mut vector {
                *x /= norm;
            }
            Ok(Arc::new(vector))
        };
        let query_vector = encode(query)?;
        let expanded_vector = if expanded == query {
            query_vector.clone()
        } else {
            encode(expanded)?
        };
        let original = Arc::new(self.source.matrix.scores(&query_vector)?);
        let expanded_scores = if expanded == query {
            original.clone()
        } else {
            Arc::new(self.source.matrix.scores(&expanded_vector)?)
        };
        Ok(ContextualScores {
            source: self.source.clone(),
            original,
            expanded: expanded_scores,
            views: self.views.clone(),
            queries: (query_vector, expanded_vector),
        })
    }
}
pub struct ContextualScores {
    source: Arc<OwnerVectorSnapshot>,
    original: Arc<Vec<f32>>,
    expanded: Arc<Vec<f32>>,
    views: Option<Arc<SourceViewSnapshot>>,
    queries: (Arc<Vec<f32>>, Arc<Vec<f32>>),
}
impl ContextualScores {
    pub fn original(&self) -> &[f32] {
        &self.original
    }
    pub fn expanded(&self) -> &[f32] {
        &self.expanded
    }
    pub fn propose(
        &self,
        owners: &[(EntityKey, Vec<Passage>)],
        limit: isize,
    ) -> Result<Vec<Candidate>> {
        if limit <= 0 {
            return Err(RetrievalError::Invalid(
                "positive contextual proposal budget required".into(),
            ));
        }
        let owners: BTreeMap<_, _> = owners.iter().map(|(k, ps)| (k, ps)).collect();
        if owners.keys().copied().collect::<BTreeSet<_>>() != self.source.owners.iter().collect()
            || self
                .source
                .owners
                .iter()
                .zip(&self.source.hashes)
                .any(|(entity, hash)| !evidence_matches(entity, hash, owners[entity]))
        {
            return Err(RetrievalError::Version(
                "contextual candidate source changed; reindex owner vectors".into(),
            ));
        }
        let peaks: Vec<_> = self
            .original
            .iter()
            .zip(self.expanded.iter())
            .map(|(&a, &b)| if a > b { a } else { b })
            .collect();
        let mut order: Vec<_> = (0..peaks.len()).collect();
        order.sort_by(|&a, &b| {
            peaks[b]
                .partial_cmp(&peaks[a])
                .expect("finite contextual scores")
        });
        order
            .into_iter()
            .take(limit as usize)
            .map(|index| {
                let entity = &self.source.owners[index];
                let passages = owners.get(entity).ok_or_else(|| {
                    RetrievalError::Version(
                        "contextual candidate source changed; reindex owner vectors".into(),
                    )
                })?;
                Ok(Candidate {
                    entity: entity.clone(),
                    passages: passages.iter().take(4).cloned().collect(),
                    signals: BTreeMap::from([("cosine_code".into(), peaks[index] as f64)]),
                    owned_regions: merge_spans(
                        &passages.iter().map(|p| p.span).collect::<Vec<_>>(),
                    ),
                })
            })
            .collect()
    }
    pub fn enrich(&self, candidates: &mut [Candidate]) -> Result<()> {
        let lookup: BTreeMap<_, _> = self
            .source
            .owners
            .iter()
            .enumerate()
            .map(|(i, key)| (key, i))
            .collect();
        for candidate in candidates.iter_mut() {
            let invalid = || {
                RetrievalError::Version(
                    "contextual candidate source changed; reindex owner vectors".into(),
                )
            };
            let &index = lookup.get(&candidate.entity).ok_or_else(invalid)?;
            if !evidence_matches(
                &candidate.entity,
                &self.source.hashes[index],
                &candidate.passages,
            ) {
                return Err(invalid());
            }
            let (a, b) = (self.original[index] as f64, self.expanded[index] as f64);
            candidate.signals.extend([
                ("cosine_code_original".into(), a),
                ("cosine_code_expanded".into(), b),
                ("cosine_code".into(), if a >= b { a } else { b }),
            ]);
        }
        if let Some(views) = &self.views {
            views.enrich(candidates, &self.queries.0, &self.queries.1)?;
        }
        Ok(())
    }
}
