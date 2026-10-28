//! Source projections contribute only after the combined owner pool is known.
use crate::{
    EntityKey, Result, RetrievalError, contextual::consistent_versions,
    description::OwnerDescription, model::evidence_matches, normalized_matrix::NormalizedMatrix,
    query::Candidate,
};
use ken_models::EncoderSpec;
use ken_text::PythonText;
use std::collections::{BTreeMap, BTreeSet};

pub const SOURCE_VIEW_NAMES: [&str; 2] = ["contract", "implementation"];
pub const SOURCE_VIEW_PROJECTION: &str =
    "own-contract-full-doc-empty-source-and-docless-owned-implementation-prefix512-v1";
pub fn owner_view_texts(description: &OwnerDescription) -> BTreeMap<String, PythonText> {
    let fields = &description.fields;
    SOURCE_VIEW_NAMES
        .into_iter()
        .map(|name| {
            let (documentation, source) = if name == "contract" {
                (fields["documentation"].clone(), PythonText::from(""))
            } else {
                (PythonText::from(""), fields["implementation"].clone())
            };
            let mut points = Vec::new();
            for value in [
                &PythonText::from(description.entity.path.clone()),
                &fields["identity"],
                &fields["signature"],
            ] {
                points.extend_from_slice(value.codepoints());
                points.push(10);
            }
            points.extend("Documentation: ".chars().map(u32::from));
            points.extend_from_slice(documentation.codepoints());
            points.extend("\nSource:\n".chars().map(u32::from));
            points.extend_from_slice(source.codepoints());
            (
                name.into(),
                PythonText::from_codepoints(points).expect("source text codepoints"),
            )
        })
        .collect()
}
#[derive(Debug)]
pub struct SourceViewSnapshot {
    pub(crate) model: EncoderSpec,
    pub(crate) generation: i64,
    pub(crate) owners: Vec<EntityKey>,
    pub(crate) hashes: Vec<String>,
    pub(crate) matrix: NormalizedMatrix,
    rows: BTreeMap<String, Vec<usize>>,
    pub(crate) query_model: EncoderSpec,
}
impl SourceViewSnapshot {
    pub fn new(
        model: EncoderSpec,
        generation: i64,
        owners: Vec<EntityKey>,
        hashes: Vec<String>,
        matrix: Vec<Vec<f32>>,
        rows: BTreeMap<String, Vec<i64>>,
        query_model: EncoderSpec,
    ) -> Result<Self> {
        Self::build(
            model,
            generation,
            owners,
            hashes,
            || {
                NormalizedMatrix::new(
                    matrix,
                    "nonempty source view vectors required",
                    "source view vectors must be finite and normalized",
                )
            },
            rows,
            query_model,
        )
    }
    pub(crate) fn from_mapped(
        model: EncoderSpec,
        generation: i64,
        owners: Vec<EntityKey>,
        hashes: Vec<String>,
        matrix: crate::npy_matrix::MappedNpy,
        rows: BTreeMap<String, Vec<i64>>,
        query_model: EncoderSpec,
    ) -> Result<Self> {
        Self::build(
            model,
            generation,
            owners,
            hashes,
            || {
                NormalizedMatrix::mapped(
                    matrix,
                    "nonempty source view vectors required",
                    "source view vectors must be finite and normalized",
                )
            },
            rows,
            query_model,
        )
    }
    fn build(
        model: EncoderSpec,
        generation: i64,
        owners: Vec<EntityKey>,
        hashes: Vec<String>,
        make_matrix: impl FnOnce() -> Result<NormalizedMatrix>,
        rows: BTreeMap<String, Vec<i64>>,
        query_model: EncoderSpec,
    ) -> Result<Self> {
        if model == query_model {
            return Err(RetrievalError::Invalid(
                "separate source views require their distinct projection identity".into(),
            ));
        }
        if generation < 0
            || owners.is_empty()
            || owners.iter().collect::<BTreeSet<_>>().len() != owners.len()
            || hashes.len() != owners.len()
            || hashes.iter().any(String::is_empty)
        {
            return Err(RetrievalError::Invalid(
                "source views require unique owners and source versions".into(),
            ));
        }
        if !consistent_versions(&owners, &hashes) {
            return Err(RetrievalError::Invalid(
                "source views contain mixed source versions".into(),
            ));
        }
        let matrix = make_matrix()?;
        if rows.keys().map(String::as_str).collect::<BTreeSet<_>>()
            != BTreeSet::from(SOURCE_VIEW_NAMES)
        {
            return Err(RetrievalError::Invalid(
                "both registered source views are required".into(),
            ));
        }
        let mut accepted = BTreeMap::new();
        for (name, indexes) in rows {
            if indexes.len() != owners.len()
                || indexes
                    .iter()
                    .any(|&i| i < 0 || i as u64 >= matrix.rows() as u64)
            {
                return Err(RetrievalError::Invalid(
                    "source view rows must identify a vector for every owner".into(),
                ));
            }
            accepted.insert(name, indexes.into_iter().map(|i| i as usize).collect());
        }
        Ok(Self {
            model,
            generation,
            owners,
            hashes,
            matrix,
            rows: accepted,
            query_model,
        })
    }
    pub fn model(&self) -> &EncoderSpec {
        &self.model
    }
    pub fn rows(&self) -> &BTreeMap<String, Vec<usize>> {
        &self.rows
    }
    pub fn matrix(&self) -> crate::normalized_matrix::MatrixView<'_> {
        self.matrix.view()
    }
    pub fn enrich(
        &self,
        candidates: &mut [Candidate],
        original: &[f32],
        expanded: &[f32],
    ) -> Result<()> {
        if candidates.is_empty() {
            return Ok(());
        }
        let lookup: BTreeMap<_, _> = self
            .owners
            .iter()
            .enumerate()
            .map(|(i, key)| (key, i))
            .collect();
        let indexes = candidates
            .iter()
            .map(|c| {
                let index = lookup.get(&c.entity).copied().ok_or_else(|| {
                    RetrievalError::Version(
                        "source view candidate is outside its source owners".into(),
                    )
                })?;
                if !evidence_matches(&c.entity, &self.hashes[index], &c.passages) {
                    return Err(RetrievalError::Version(
                        "source view candidate source changed; reindex source views".into(),
                    ));
                }
                Ok(index)
            })
            .collect::<Result<Vec<_>>>()?;
        for name in SOURCE_VIEW_NAMES {
            let rows: Vec<_> = indexes.iter().map(|&i| self.rows[name][i]).collect();
            let a = self.matrix.gathered_scores(&rows, original)?;
            let b = if std::ptr::eq(original, expanded) {
                None
            } else {
                Some(self.matrix.gathered_scores(&rows, expanded)?)
            };
            for (i, candidate) in candidates.iter_mut().enumerate() {
                candidate
                    .signals
                    .insert(format!("cosine_view_{name}_original"), a[i] as f64);
                candidate.signals.insert(
                    format!("cosine_view_{name}_expanded"),
                    b.as_ref().unwrap_or(&a)[i] as f64,
                );
            }
        }
        Ok(())
    }
}
