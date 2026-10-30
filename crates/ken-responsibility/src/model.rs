use ken_text::PythonText;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeSet;
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Symbol {
    pub path: String,
    pub qualname: String,
    pub kind: String,
    pub line: usize,
    pub end_line: usize,
    pub documentation: PythonText,
    pub sha256: String,
    #[serde(default)]
    pub calls: Vec<(String, usize)>,
    #[serde(default)]
    pub refreshed: bool,
    pub doc_scope: String,
    pub implementation_line: usize,
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Evidence {
    pub reasoner: String,
    pub direction: String,
    pub strength: f64,
    pub explanation: PythonText,
    #[serde(default)]
    pub assumption: PythonText,
}
pub struct Inquiry {
    pub wording: String,
    pub terms: BTreeSet<String>,
    pub similarity: f64,
}
pub trait Reasoner {
    fn assess(&self, inquiry: &Inquiry, symbol: &Symbol) -> crate::Result<Vec<Evidence>>;
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Confidence {
    pub score: f64,
    pub band: String,
    pub calibrated: bool,
    pub probability: Option<f64>,
    pub policy: String,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct IndexedCandidate {
    pub path: String,
    pub qualname: String,
    pub kind: String,
    pub name: String,
    pub docstring: Option<String>,
    pub content_hash: Vec<u8>,
    pub vec_slot: Option<i64>,
    pub embedding: Option<Vec<u8>>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SourceEvidence {
    pub sha256: String,
    pub index_changed: bool,
    pub documentation_scope: String,
    pub documentation_kind: String,
    pub behavior_verified: bool,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Snippet {
    pub start_line: usize,
    pub end_line: usize,
    pub content: PythonText,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Preview {
    pub end_line: usize,
    pub snippets: Vec<Snippet>,
    pub truncated: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub preview_unavailable: Option<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Candidate {
    pub symbol: String,
    pub path: String,
    pub line: usize,
    pub kind: String,
    pub status: String,
    pub confidence: Confidence,
    pub matched_formulation: String,
    pub documentation: PythonText,
    pub evidence: Vec<Evidence>,
    pub assumptions: Vec<PythonText>,
    pub source: SourceEvidence,
    pub inspect: Value,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub end_line: Option<usize>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub snippets: Option<Vec<Snippet>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub truncated: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub preview_unavailable: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub structure: Option<Value>,
}
impl Candidate {
    pub(crate) fn preview(&mut self, preview: Preview) {
        self.end_line = Some(preview.end_line);
        self.snippets = Some(preview.snippets);
        self.truncated = Some(preview.truncated);
        self.preview_unavailable = preview.preview_unavailable;
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WhoReport {
    pub ok: bool,
    pub question: String,
    pub hypotheses: Vec<String>,
    pub status: String,
    pub candidates: Vec<Candidate>,
    pub counterevidence: Vec<Candidate>,
    pub assessment: Value,
    pub coverage: Value,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub responsibility_map: Option<Value>,
}
impl WhoReport {
    pub fn to_json(&self) -> crate::Result<Value> {
        Ok(serde_json::from_str(&self.to_json_string()?)?)
    }
    pub fn to_json_string(&self) -> crate::Result<String> {
        Ok(serde_json::to_string(self)?)
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct WhoRequest {
    pub question: String,
    pub path: String,
    pub hypotheses: Vec<String>,
    pub limit: i64,
    pub include_tests: bool,
}
impl Default for WhoRequest {
    fn default() -> Self {
        Self {
            question: String::new(),
            path: ".".into(),
            hypotheses: vec![],
            limit: 3,
            include_tests: false,
        }
    }
}
#[derive(Clone, Debug)]
pub struct LiveScores {
    pub slots: Vec<i64>,
    pub scores: Vec<f32>,
}
#[derive(Clone, Debug)]
pub struct RankedRows {
    pub kept: Vec<usize>,
    pub scores: Vec<f32>,
}
