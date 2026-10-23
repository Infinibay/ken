//! Bounded view text uses the actual encoder's token counter.
use crate::{DocumentEncoder, Passage, Result, RetrievalError, projections::View};
use ken_models::RetrievalProfile;
fn prefix(text: &str, budget: i64, encoder: &dyn DocumentEncoder) -> Result<String> {
    if budget <= 0 {
        return Ok(String::new());
    }
    if encoder.token_count(text)? <= budget as usize {
        return Ok(text.into());
    }
    let mut positions: Vec<_> = text.char_indices().map(|(i, _)| i).collect();
    positions.push(text.len());
    let (mut low, mut high) = (0, positions.len() - 1);
    while low < high {
        let middle = (low + high).div_ceil(2);
        if encoder.token_count(&text[..positions[middle]])? <= budget as usize {
            low = middle
        } else {
            high = middle - 1
        }
    }
    Ok(text[..positions[low]].into())
}
pub fn bounded_passage_text(
    passage: &Passage,
    view: View,
    profile: &RetrievalProfile,
    encoder: &dyn DocumentEncoder,
) -> Result<String> {
    let fields = passage.fields.scalar()?;
    let [
        (_, identity),
        (_, signature),
        (_, documentation),
        (_, body),
        (_, path),
    ] = fields;
    let sequence = match view {
        View::Identity => profile.identity.sequence_length,
        View::Behavior => profile.behavior.sequence_length,
    };
    let available = i64::try_from(sequence)
        .map_err(|_| RetrievalError::Invalid("sequence budget exceeds integer range".into()))?
        - 6;
    if available < 32 {
        return Err(RetrievalError::Invalid(
            "encoder sequence budget is too small for code evidence".into(),
        ));
    }
    let mut header = format!("{identity}\n{path}\n{signature}");
    if view == View::Identity {
        return prefix(&header, available.min(192), encoder);
    }
    let body = prefix(
        &body,
        (profile.max_tokens as i64).min(available - 24),
        encoder,
    )?;
    header = prefix(
        &header,
        128.min(available - encoder.token_count(&format!("\nSource:\n{body}"))? as i64),
        encoder,
    )?;
    let mut text = format!("{header}\nSource:\n{body}");
    while encoder.token_count(&text)? > available as usize && !header.is_empty() {
        header.pop();
        text = format!("{header}\nSource:\n{body}")
    }
    let remaining = available - encoder.token_count(&format!("{text}\nDocumentation:\n"))? as i64;
    let documentation = prefix(&documentation, 64.min(remaining), encoder)?;
    if !documentation.is_empty() {
        text += &format!("\nDocumentation:\n{documentation}")
    }
    if encoder.token_count(&text)? > available as usize {
        return Err(RetrievalError::Invalid(
            "projection exceeds its actual tokenizer budget".into(),
        ));
    }
    Ok(text)
}
