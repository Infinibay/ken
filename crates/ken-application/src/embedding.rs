//! Small application adapters; domains retain persistence and ranking policy.
use ken_retrieval::{DocumentEncoder, query_encoder::QueryEncoder, vector_math::NativeVectorMath};
use ken_text::PythonText;
use std::{cell::RefCell, rc::Rc};
/// Query encoding is injectable; cosine/ordering always use the shared owner.
pub struct IntentVectorAdapter<'a> {
    query: Rc<dyn QueryEncoder + 'a>,
    math: Option<NativeVectorMath>,
}
impl<'a> IntentVectorAdapter<'a> {
    pub fn new(query: Rc<dyn QueryEncoder + 'a>) -> Self {
        Self { query, math: None }
    }
    fn math(&mut self) -> ken_history::Result<NativeVectorMath> {
        if self.math.is_none() {
            self.math = Some(NativeVectorMath::platform().map_err(history_error)?);
        }
        Ok(self.math.expect("retained numerical owner"))
    }
}
fn history_error(error: impl std::fmt::Display) -> ken_history::HistoryError {
    ken_history::HistoryError::Invalid(format!("native embeddings: {error}"))
}
impl ken_history::intent::IntentVectors for IntentVectorAdapter<'_> {
    fn embed_query(&mut self, text: &str) -> ken_history::Result<Vec<f32>> {
        self.query.embed_query(&text.into()).map_err(history_error)
    }
    fn rank(
        &mut self,
        query: &[f32],
        rows: &[Vec<f32>],
    ) -> ken_history::Result<ken_history::intent::Ranking> {
        if rows.is_empty() {
            return Ok(ken_history::intent::Ranking {
                scores: vec![],
                order: vec![],
            });
        }
        let count = rows
            .len()
            .checked_mul(query.len())
            .ok_or_else(|| history_error("embedding matrix dimensions overflow"))?;
        if rows.iter().any(|row| row.len() != query.len()) {
            return Err(history_error(
                "compatible embedding row dimensions required",
            ));
        }
        let mut matrix = Vec::new();
        matrix.try_reserve_exact(count).map_err(history_error)?;
        matrix.extend(rows.iter().flatten().copied());
        let math = self.math()?;
        let scores = math
            .cosine_against(query, &matrix, rows.len(), query.len())
            .map_err(history_error)?;
        let order = math
            .argsort_descending_f32(&scores)
            .map_err(history_error)?;
        Ok(ken_history::intent::Ranking { scores, order })
    }
}
/// Lazy construction lets finding writes survive optional numerical failures.
#[derive(Default)]
pub struct FindingVectorMath {
    math: RefCell<Option<NativeVectorMath>>,
}
fn finding_error(error: impl std::fmt::Display) -> ken_knowledge::Error {
    ken_knowledge::Error::Invalid(format!("native embeddings: {error}"))
}
impl FindingVectorMath {
    fn math(&self) -> ken_knowledge::Result<NativeVectorMath> {
        let mut slot = self.math.borrow_mut();
        if slot.is_none() {
            *slot = Some(NativeVectorMath::platform().map_err(finding_error)?);
        }
        Ok(slot.expect("retained numerical owner"))
    }
}
impl ken_knowledge::findings::VectorMath for FindingVectorMath {
    fn query_norm(&self, vector: &[f32]) -> ken_knowledge::Result<f32> {
        self.math()?.query_norm(vector).map_err(finding_error)
    }
    fn row_norm(&self, row: &[f32]) -> ken_knowledge::Result<f32> {
        self.math()?
            .row_norms(row, 1, row.len())
            .map_err(finding_error)?
            .into_iter()
            .next()
            .ok_or_else(|| finding_error("row norm result missing"))
    }
    fn scores(
        &self,
        matrix: &[f32],
        rows: usize,
        query: &[f32],
    ) -> ken_knowledge::Result<Vec<f32>> {
        self.math()?
            .scores(matrix, rows, query.len(), query)
            .map_err(finding_error)
    }
    fn symmetric_product(
        &self,
        matrix: &[f32],
        rows: usize,
        width: usize,
    ) -> ken_knowledge::Result<Vec<f32>> {
        self.math()?
            .product(matrix, rows, width, matrix, rows)
            .map_err(finding_error)
    }
}
/// A finding is a document. Only this best-effort write-side operation converts
/// an embedding failure to None; recall and ranking keep explicit errors.
pub fn finding_embedding(
    documents: &dyn DocumentEncoder,
    topic: &str,
    content: &str,
) -> Option<Vec<f32>> {
    let topic = PythonText::from(topic).trimmed().to_utf8()?;
    let content = PythonText::from(content).trimmed().to_utf8()?;
    if topic.is_empty() || content.is_empty() {
        return None;
    }
    let text = format!(
        "{topic}\n\n{}",
        content.chars().take(1024).collect::<String>()
    );
    documents.embed_passages(&[&text]).ok()?.into_iter().next()
}
