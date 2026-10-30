//! Each channel owns its observations and raw scores, never final confidence.
pub(crate) mod behavioral;
mod lexical;
mod literal;
mod mentions;
mod semantic;
use crate::{ContextNumerics, Error, Result, VectorScores};
pub use behavioral::{SimilarPrompt, predictive_scores, reactive_scores, similar_past_sessions};
pub(crate) use behavioral::{
    base_rate_discount, file_base_rates, historical_file_scores, pattern_multiplier,
};
pub use lexical::lexical_scores;
pub use literal::literal_content_scores;
pub use mentions::{explicit_mentions, source_path_mentions};
pub use semantic::{doc_intent_scores, finding_scores, fuzzy_scores};
pub(crate) fn inline(
    numerics: &mut dyn ContextNumerics,
    q: &[f32],
    blobs: &[Vec<u8>],
) -> Result<VectorScores> {
    let result = numerics.rank_inline(q, blobs)?;
    let unique = result
        .kept
        .iter()
        .collect::<std::collections::BTreeSet<_>>();
    if result.kept.len() != result.scores.len()
        || unique.len() != result.kept.len()
        || result.kept.iter().any(|i| *i >= blobs.len())
    {
        return Err(Error::Invalid(
            "context numerical provider returned incompatible row identities".into(),
        ));
    }
    Ok(result)
}
