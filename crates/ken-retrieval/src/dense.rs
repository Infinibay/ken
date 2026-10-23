//! Immutable vector rows, stable source-owner maxima and their supporting evidence.
use crate::{
    EntityKey, Passage, Result, RetrievalError,
    embedding_store::VectorView,
    query::{Candidate, Signals},
};
use std::collections::{HashMap, HashSet};
pub struct DenseView {
    passages: Vec<Passage>,
    matrix: Vec<f32>,
    entities: Vec<EntityKey>,
    labels: Vec<usize>,
    dimension: usize,
}
impl DenseView {
    pub fn new(passages: Vec<(i64, Passage)>, vectors: VectorView) -> Result<Self> {
        let dimension = vectors.matrix.first().map_or(0, Vec::len);
        if vectors.ids.len() != vectors.matrix.len()
            || vectors
                .matrix
                .iter()
                .any(|row| row.len() != dimension || row.iter().any(|n| !n.is_finite()))
        {
            return Err(RetrievalError::Version(
                "invalid vector view dimensions/values; reindex the retrieval profile".into(),
            ));
        }
        let by_id: HashMap<_, _> = passages.into_iter().collect();
        let mut owned = Vec::with_capacity(vectors.ids.len());
        let mut entities = Vec::new();
        let mut indices = HashMap::new();
        let mut labels = Vec::new();
        for id in vectors.ids {
            let passage = by_id.get(&id).ok_or_else(|| {
                RetrievalError::Version(
                    "vector owner changed; reindex the retrieval profile".into(),
                )
            })?;
            let next = indices.len();
            let label = *indices.entry(passage.entity.clone()).or_insert_with(|| {
                entities.push(passage.entity.clone());
                next
            });
            labels.push(label);
            owned.push(passage.clone());
        }
        Ok(Self {
            passages: owned,
            matrix: vectors.matrix.into_iter().flatten().collect(),
            entities,
            labels,
            dimension,
        })
    }
    pub fn search(&self, query: &[f32], view: &str, limit: isize) -> Result<Vec<Candidate>> {
        if query.len() != self.dimension {
            return Err(RetrievalError::Version(
                "query/vector dimensions differ; reindex the retrieval profile".into(),
            ));
        }
        if query.iter().any(|n| !n.is_finite()) {
            return Err(RetrievalError::Invalid(
                "encoder returned an invalid query vector".into(),
            ));
        }
        let math = crate::dense_math::DenseMath::platform()?;
        let norm = math.norm(query)?;
        if norm <= 0. {
            return Err(RetrievalError::Invalid(
                "encoder returned an invalid query vector".into(),
            ));
        }
        let normalized: Vec<_> = query.iter().map(|n| n / norm).collect();
        let scores = math.scores(&self.matrix, self.passages.len(), &normalized)?;
        let mut peaks = vec![f32::NEG_INFINITY; self.entities.len()];
        for (&label, &score) in self.labels.iter().zip(&scores) {
            peaks[label] = peaks[label].max(score)
        }
        let mut selected: Vec<_> = (0..self.entities.len()).collect();
        selected.sort_by(|&a, &b| {
            peaks[b]
                .partial_cmp(&peaks[a])
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let count = if limit >= 0 {
            (limit as usize).min(selected.len())
        } else {
            selected.len().saturating_sub(limit.unsigned_abs())
        };
        selected.truncate(count);
        let selected_set: HashSet<_> = selected.iter().copied().collect();
        let mut rows: Vec<_> = self
            .labels
            .iter()
            .enumerate()
            .filter_map(|(i, label)| selected_set.contains(label).then_some(i))
            .collect();
        rows.sort_by(|&a, &b| {
            scores[b]
                .partial_cmp(&scores[a])
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let signal = format!("cosine_{view}");
        let mut evidence: HashMap<usize, Vec<Passage>> =
            selected.iter().map(|&owner| (owner, Vec::new())).collect();
        for row in rows {
            let owned = evidence
                .get_mut(&self.labels[row])
                .expect("selected source owner");
            if owned.len() < 4 {
                let mut passage = self.passages[row].clone();
                passage.signals.insert(signal.clone(), scores[row] as f64);
                owned.push(passage)
            }
        }
        Ok(selected
            .into_iter()
            .map(|owner| Candidate {
                entity: self.entities[owner].clone(),
                passages: evidence.remove(&owner).expect("selected evidence"),
                signals: Signals::from([(signal.clone(), peaks[owner] as f64)]),
                owned_regions: Vec::new(),
            })
            .collect())
    }
}
