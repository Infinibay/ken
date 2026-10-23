//! Complete lexical views belong to one canonical owner and one source version.
use crate::{EntityKey, Passage, Result, RetrievalError, text_patterns as p};
use ken_text::{PythonText, unicode::whitespace};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap};
pub const DESCRIPTION_VERSION: usize = 1;
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct OwnerDescription {
    pub entity: EntityKey,
    pub source_hash: String,
    pub fields: BTreeMap<String, PythonText>,
    pub owned_lines: usize,
    pub implementation_lines: usize,
    pub executable_lines: usize,
    pub comment_lines: usize,
    pub regions: usize,
    pub passages: Vec<Passage>,
}
fn join(values: &[PythonText]) -> PythonText {
    let mut points = Vec::new();
    for (i, value) in values.iter().enumerate() {
        if i > 0 {
            points.push(10);
        }
        points.extend_from_slice(value.codepoints());
    }
    p::text(&points)
}
pub fn describe_owner(passages: &[Passage]) -> Result<OwnerDescription> {
    let Some(first) = passages.first() else {
        return Err(RetrievalError::Invalid(
            "owner description requires passages".into(),
        ));
    };
    if passages.iter().any(|p| p.entity != first.entity) {
        return Err(RetrievalError::Invalid(
            "mixed owner identities in description".into(),
        ));
    }
    if passages.iter().any(|p| p.source_hash != first.source_hash) {
        return Err(RetrievalError::Invalid(
            "mixed source versions in description".into(),
        ));
    }
    let mut positions = HashMap::new();
    let mut ordered: Vec<Passage> = Vec::new();
    for passage in passages {
        let span = (passage.span.start_line, passage.span.end_line);
        if let Some(&i) = positions.get(&span) {
            ordered[i] = passage.clone();
        } else {
            positions.insert(span, ordered.len());
            ordered.push(passage.clone());
        }
    }
    ordered.sort_by_key(|p| p.span.start_line);
    let mut unique: BTreeMap<&str, Vec<PythonText>> = BTreeMap::new();
    for passage in &ordered {
        for (name, value) in passage.fields.entries() {
            let values = unique.entry(name).or_default();
            if !values.contains(value) {
                values.push(value.clone());
            }
        }
    }
    let mut fields: BTreeMap<String, PythonText> = unique
        .into_iter()
        .map(|(name, values)| (name.into(), join(&values)))
        .collect();
    let mut implementation = Vec::new();
    for passage in &ordered {
        let start = passage
            .implementation_start_line
            .filter(|n| *n != 0)
            .unwrap_or(passage.span.start_line);
        let offset = start.saturating_sub(passage.span.start_line);
        implementation.extend(
            passage
                .fields
                .body
                .codepoints()
                .split(|c| *c == 10)
                .skip(offset)
                .map(p::text),
        );
    }
    let comments: Vec<_> = implementation
        .iter()
        .filter(|line| p::has(r"^\s*(?:#|//|/\*|\*|--)", false, line))
        .cloned()
        .collect();
    let executable: Vec<_> = implementation
        .iter()
        .filter(|line| {
            line.codepoints()
                .iter()
                .any(|c| !char::from_u32(*c).is_some_and(whitespace))
                && !p::has(r"^\s*(?:#|//|/\*|\*|--)", false, line)
        })
        .cloned()
        .collect();
    let calls: Vec<_> = p::captures(r"[\w$.]+(?=\s*\()", false, &join(&executable))
        .into_iter()
        .map(|m| m.whole)
        .collect();
    let returns: Vec<_> = executable
        .iter()
        .filter(|line| p::has(r"\b(?:return|throw|raise|yield)\b", false, line))
        .cloned()
        .collect();
    for (name, value) in [
        ("implementation", join(&implementation)),
        ("comments", join(&comments)),
        ("executable", join(&executable)),
        ("calls", join(&calls)),
        ("returns", join(&returns)),
    ] {
        fields.insert(name.into(), value);
    }
    let owned_lines = ordered
        .iter()
        .try_fold(0usize, |total, p| {
            total.checked_add(p.span.end_line - p.span.start_line + 1)
        })
        .ok_or_else(|| {
            RetrievalError::Invalid("owner line count exceeds the native source limit".into())
        })?;
    Ok(OwnerDescription {
        entity: first.entity.clone(),
        source_hash: first.source_hash.clone(),
        fields,
        owned_lines,
        implementation_lines: implementation.len(),
        executable_lines: executable.len(),
        comment_lines: comments.len(),
        regions: ordered.len(),
        passages: ordered,
    })
}
