//! Whole owned-code relevance complements card scores without changing membership.
use crate::{
    Result, RetrievalError, description::OwnerDescription, paired_reranker::PairedReranker,
};
use ken_text::{PythonText, unicode};
use serde::Serialize;
use serde_json::Value;

#[derive(Clone, Debug, Serialize)]
pub struct SymbolRelevance {
    pub order: Vec<usize>,
    #[serde(serialize_with = "crate::paired_reranker::serialize_scores")]
    pub code_scores: Vec<f64>,
    #[serde(serialize_with = "crate::paired_reranker::serialize_scores")]
    pub mean_scores: Vec<f64>,
    pub code_view_used: Vec<bool>,
    pub additional_inference: Value,
}
pub fn complete_code_view(description: &OwnerDescription) -> Result<Option<PythonText>> {
    let body = description
        .fields
        .get("executable")
        .ok_or_else(|| RetrievalError::MissingField("executable".into()))?;
    let signature = description
        .fields
        .get("signature")
        .ok_or_else(|| RetrievalError::MissingField("signature".into()))?;
    let title = format!(
        "symbol {} {}\n",
        description.entity.path,
        description.entity.qualname.as_deref().unwrap_or("None")
    );
    let mut points = title.chars().map(u32::from).collect::<Vec<_>>();
    points.extend_from_slice(signature.codepoints());
    points.extend("\nImplementation:\n".chars().map(u32::from));
    points.extend_from_slice(body.codepoints());
    if points.len() > 12000 {
        return Ok(None);
    }
    // Surrogates cannot be line boundaries. Substitute only for counting while
    // retaining the original points in the returned projection.
    let lines = body
        .codepoints()
        .iter()
        .map(|&p| char::from_u32(p).unwrap_or('\u{fffd}'))
        .collect::<String>();
    if unicode::splitlines(&lines).len() > 64 {
        return Ok(None);
    }
    Ok(Some(
        PythonText::from_codepoints(points).expect("owned Python text points"),
    ))
}
pub fn rank_symbol_views(
    query: &PythonText,
    descriptions: &[OwnerDescription],
    original_scores: &[f64],
    neural: &dyn PairedReranker,
) -> Result<SymbolRelevance> {
    if descriptions.len() != original_scores.len() || descriptions.len() > 10 {
        return Err(RetrievalError::Invalid(
            "one original score per native top10 symbol required".into(),
        ));
    }
    if original_scores.iter().any(|s| !s.is_finite()) {
        return Err(RetrievalError::Invalid(
            "finite original symbol scores required".into(),
        ));
    }
    let mut fresh = Vec::new();
    let mut accepted = Vec::new();
    for description in descriptions {
        if let Some(view) = complete_code_view(description)?
            && neural.pair_fits(query, &view)?
        {
            let index = match fresh.iter().position(|old| old == &view) {
                Some(i) => i,
                None => {
                    fresh.push(view);
                    fresh.len() - 1
                }
            };
            accepted.push(Some(index));
            continue;
        }
        accepted.push(None);
    }
    let result = neural.score(query, &fresh)?;
    if result.scores.len() != fresh.len() || result.scores.iter().any(|s| !s.is_finite()) {
        return Err(RetrievalError::Invalid(
            "one finite score per complete code view required".into(),
        ));
    }
    let code_scores = accepted
        .iter()
        .enumerate()
        .map(|(i, index)| index.map_or(original_scores[i], |j| result.scores[j]))
        .collect::<Vec<_>>();
    let mean_scores = original_scores
        .iter()
        .zip(&code_scores)
        .map(|(original, code)| (original + code) / 2.)
        .collect::<Vec<_>>();
    let mut order = (0..descriptions.len()).collect::<Vec<_>>();
    order.sort_by(|&a, &b| {
        mean_scores[b]
            .partial_cmp(&mean_scores[a])
            .expect("finite inputs cannot produce a NaN mean")
    });
    Ok(SymbolRelevance {
        order,
        code_scores,
        mean_scores,
        code_view_used: accepted.iter().map(Option::is_some).collect(),
        additional_inference: result.details,
    })
}
