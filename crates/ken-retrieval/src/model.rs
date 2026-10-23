use crate::{Result, RetrievalError};
use ken_text::PythonText;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(try_from = "RawSpan")]
pub struct Span {
    pub start_line: usize,
    pub end_line: usize,
}
#[derive(Deserialize)]
struct RawSpan {
    start_line: usize,
    end_line: usize,
}
impl TryFrom<RawSpan> for Span {
    type Error = RetrievalError;
    fn try_from(s: RawSpan) -> Result<Self> {
        Self::new(s.start_line, s.end_line)
    }
}
impl Span {
    pub fn new(start_line: usize, end_line: usize) -> Result<Self> {
        if start_line == 0 || start_line > end_line {
            return Err(RetrievalError::Invalid(
                "invalid inclusive source span".into(),
            ));
        }
        Ok(Self {
            start_line,
            end_line,
        })
    }
}
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub struct EntityKey {
    pub path: String,
    pub kind: String,
    pub qualname: Option<String>,
    pub owner: Option<String>,
    pub definition_ordinal: usize,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct PassageFields {
    pub identity: PythonText,
    pub signature: PythonText,
    pub documentation: PythonText,
    pub body: PythonText,
    pub path: PythonText,
}
impl PassageFields {
    pub fn entries(&self) -> [(&'static str, &PythonText); 5] {
        [
            ("identity", &self.identity),
            ("signature", &self.signature),
            ("documentation", &self.documentation),
            ("body", &self.body),
            ("path", &self.path),
        ]
    }
    pub fn scalar(&self) -> Result<[(&'static str, String); 5]> {
        let mut out = Vec::new();
        for (k, v) in self.entries() {
            out.push((
                k,
                v.to_utf8().ok_or_else(|| {
                    RetrievalError::Invalid(
                        "non-scalar source field cannot be written as SQLite UTF-8".into(),
                    )
                })?,
            ))
        }
        Ok(out.try_into().expect("five fields"))
    }
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Passage {
    pub entity: EntityKey,
    pub span: Span,
    pub fields: PassageFields,
    pub source_hash: String,
    pub entity_span: Span,
    pub language: String,
    pub role: String,
    pub split_reason: Option<String>,
    pub signals: BTreeMap<String, f64>,
    pub implementation_start_line: Option<usize>,
}

/// Scores may cross an API boundary only with evidence from their pinned owner/source.
pub(crate) fn evidence_matches(
    entity: &EntityKey,
    source_hash: &str,
    passages: &[Passage],
) -> bool {
    !passages.is_empty()
        && passages
            .iter()
            .all(|p| p.entity == *entity && p.source_hash == source_hash)
}
