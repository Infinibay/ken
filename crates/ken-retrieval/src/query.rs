//! Validated immutable requests and owner proposals shared by retrieval channels.
use crate::{EntityKey, Passage, Result, RetrievalError, Span};
use ken_text::{PythonText, unicode::whitespace};
use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use std::collections::BTreeMap;
pub type Signals = BTreeMap<String, f64>;
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct SearchOptions {
    #[serde(deserialize_with = "query_text")]
    pub query: PythonText,
    pub target: String,
    pub purpose: String,
    pub limit: isize,
    pub max_chars: isize,
    pub explain: bool,
    pub piece_kind: Option<String>,
}
impl Default for SearchOptions {
    fn default() -> Self {
        Self {
            query: "".into(),
            target: "symbol".into(),
            purpose: "auto".into(),
            limit: 10,
            max_chars: 12000,
            explain: false,
            piece_kind: None,
        }
    }
}
/// Unlike the legacy text codec, public JSON strings join valid escape pairs.
fn query_text<'de, D: Deserializer<'de>>(
    deserializer: D,
) -> std::result::Result<PythonText, D::Error> {
    let text = PythonText::deserialize(deserializer)?;
    let mut input = text.codepoints().iter().copied().peekable();
    let mut points = Vec::new();
    while let Some(point) = input.next() {
        if (0xd800..=0xdbff).contains(&point)
            && input
                .peek()
                .is_some_and(|low| (0xdc00..=0xdfff).contains(low))
        {
            let low = input.next().expect("validated low surrogate");
            points.push(0x10000 + ((point - 0xd800) << 10) + (low - 0xdc00));
        } else {
            points.push(point)
        }
    }
    Ok(PythonText::from_codepoints(points).expect("validated text points"))
}
#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(transparent)]
pub struct SearchRequest(SearchOptions);
impl<'de> Deserialize<'de> for SearchRequest {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> std::result::Result<Self, D::Error> {
        SearchOptions::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}
impl TryFrom<SearchOptions> for SearchRequest {
    type Error = RetrievalError;
    fn try_from(options: SearchOptions) -> Result<Self> {
        let request = Self(options);
        request.validate()?;
        Ok(request)
    }
}
impl SearchRequest {
    pub fn new(query: impl Into<PythonText>) -> Result<Self> {
        SearchOptions {
            query: query.into(),
            ..Default::default()
        }
        .try_into()
    }
    pub fn validate(&self) -> Result<()> {
        let options = &self.0;
        if options
            .query
            .codepoints()
            .iter()
            .all(|&point| char::from_u32(point).is_some_and(whitespace))
            || options.limit <= 0
            || options.max_chars <= 0
        {
            return Err(RetrievalError::Invalid(
                "query and positive result/output budgets required".into(),
            ));
        }
        if !matches!(options.target.as_str(), "file" | "symbol" | "passage") {
            return Err(RetrievalError::Invalid("unknown search target".into()));
        }
        if !matches!(
            options.purpose.as_str(),
            "auto" | "implementation" | "usage" | "tests" | "documentation"
        ) {
            return Err(RetrievalError::Invalid("unknown search purpose".into()));
        }
        if options
            .piece_kind
            .as_deref()
            .is_some_and(|kind| !matches!(kind, "class" | "module" | "symbol" | "file"))
        {
            return Err(RetrievalError::Invalid(
                "unknown requested piece kind".into(),
            ));
        }
        Ok(())
    }
    pub fn query(&self) -> &PythonText {
        &self.0.query
    }
    pub fn with_query(&self, query: PythonText) -> Result<Self> {
        let mut options = self.0.clone();
        options.query = query;
        options.try_into()
    }
    pub fn with_piece_kind(&self, kind: &str) -> Result<Self> {
        let mut options = self.0.clone();
        options.piece_kind = Some(kind.into());
        options.try_into()
    }
    pub fn target(&self) -> &str {
        &self.0.target
    }
    pub fn purpose(&self) -> &str {
        &self.0.purpose
    }
    pub fn limit(&self) -> usize {
        self.0.limit as usize
    }
    pub fn max_chars(&self) -> usize {
        self.0.max_chars as usize
    }
    pub fn explain(&self) -> bool {
        self.0.explain
    }
    pub fn piece_kind(&self) -> Option<&str> {
        self.0.piece_kind.as_deref()
    }
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Candidate {
    pub entity: EntityKey,
    pub passages: Vec<Passage>,
    #[serde(default)]
    pub signals: Signals,
    #[serde(default)]
    pub owned_regions: Vec<Span>,
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct CodeMatch {
    pub entity: EntityKey,
    pub score: f64,
    pub evidence: Vec<Passage>,
    pub source_hash: String,
    pub signals: Signals,
    pub owned_regions: Vec<Span>,
}
pub fn merge_spans(spans: &[Span]) -> Vec<Span> {
    let mut ordered = spans.to_vec();
    ordered.sort_unstable();
    ordered.dedup();
    let mut merged: Vec<Span> = Vec::new();
    for span in ordered {
        if let Some(previous) = merged
            .last_mut()
            .filter(|p| span.start_line <= p.end_line.saturating_add(1))
        {
            previous.end_line = previous.end_line.max(span.end_line)
        } else {
            merged.push(span)
        }
    }
    merged
}
