//! Pair capacity and raw relevance scores share one explicitly owned model.
use crate::{Result, RetrievalError};
use ken_models::OnnxReranker;
use ken_text::PythonText;
use serde::{Serialize, Serializer};
use serde_json::Value;
use std::sync::Arc;

#[derive(Clone, Debug, Serialize)]
pub struct NeuralScores {
    #[serde(serialize_with = "serialize_scores")]
    pub scores: Vec<f64>,
    pub details: Value,
}
pub(crate) fn serialize_scores<S: Serializer>(
    scores: &[f64],
    serializer: S,
) -> std::result::Result<S::Ok, S::Error> {
    scores
        .iter()
        .copied()
        .map(crate::number_json::value)
        .collect::<Vec<_>>()
        .serialize(serializer)
}
pub trait PairedReranker {
    fn pair_fits(&self, query: &PythonText, document: &PythonText) -> Result<bool>;
    fn score(&self, query: &PythonText, documents: &[PythonText]) -> Result<NeuralScores>;
}
pub struct OnnxPairedReranker(pub Arc<OnnxReranker>);
fn scalar(text: &PythonText) -> Result<String> {
    text.to_utf8().ok_or_else(|| {
        RetrievalError::Invalid("non-scalar Unicode cannot be passed to the paired model".into())
    })
}
impl PairedReranker for OnnxPairedReranker {
    fn pair_fits(&self, query: &PythonText, document: &PythonText) -> Result<bool> {
        Ok(self.0.pair_fits(&scalar(query)?, &scalar(document)?)?)
    }
    fn score(&self, query: &PythonText, documents: &[PythonText]) -> Result<NeuralScores> {
        // Model empty scoring has no scalar-query or resource precondition.
        let pool = if documents.is_empty() {
            self.0.score("", &[])?
        } else {
            let query = scalar(query)?;
            let documents = documents.iter().map(scalar).collect::<Result<Vec<_>>>()?;
            self.0.score(
                &query,
                &documents.iter().map(String::as_str).collect::<Vec<_>>(),
            )?
        };
        Ok(NeuralScores {
            scores: pool.scores.into_iter().map(f64::from).collect(),
            details: serde_json::to_value(pool.details)?,
        })
    }
}
