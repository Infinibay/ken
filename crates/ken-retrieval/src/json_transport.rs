//! Python-compatible strings at the public JSON transport boundary.
use crate::{Result, RetrievalError};
use ken_text::PythonText;
/// Python json.loads joins valid escaped pairs in every string, preserving lone
/// surrogates. Apply that public transport rule without changing the legacy codec.
pub fn python_strings(input: &str) -> Result<String> {
    let mut out = String::with_capacity(input.len());
    let mut cursor = 0;
    while let Some(offset) = input[cursor..].find('"') {
        let start = cursor + offset;
        out.push_str(&input[cursor..start]);
        let mut end = start + 1;
        let bytes = input.as_bytes();
        while end < bytes.len() {
            if bytes[end] == b'\\' {
                end += 2;
            } else if bytes[end] == b'"' {
                break;
            } else {
                end += 1;
            }
        }
        if end >= bytes.len() {
            return Err(RetrievalError::Invalid("unterminated JSON string".into()));
        }
        let value: PythonText = serde_json::from_str(&input[start..=end])?;
        let mut points = Vec::new();
        let mut source = value.codepoints().iter().copied().peekable();
        while let Some(point) = source.next() {
            if (0xd800..=0xdbff).contains(&point)
                && source
                    .peek()
                    .is_some_and(|low| (0xdc00..=0xdfff).contains(low))
            {
                let low = source.next().expect("low surrogate");
                points.push(0x10000 + ((point - 0xd800) << 10) + (low - 0xdc00));
            } else {
                points.push(point);
            }
        }
        out.push_str(&serde_json::to_string(
            &PythonText::from_codepoints(points).expect("JSON codepoints"),
        )?);
        cursor = end + 1;
    }
    out.push_str(&input[cursor..]);
    Ok(out)
}
