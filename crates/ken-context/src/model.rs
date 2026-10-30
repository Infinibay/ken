use crate::Result;
use ken_text::PythonText;
use rusqlite::Connection;
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
};
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct RankedItem {
    pub target: PythonText,
    pub target_type: String,
    pub score: f64,
    pub reason: PythonText,
}
impl RankedItem {
    pub fn file(target: impl Into<PythonText>, score: f64, reason: impl Into<PythonText>) -> Self {
        Self {
            target: target.into(),
            target_type: "file".into(),
            score,
            reason: reason.into(),
        }
    }
    pub fn symbol(
        target: impl Into<PythonText>,
        score: f64,
        reason: impl Into<PythonText>,
    ) -> Self {
        Self {
            target: target.into(),
            target_type: "symbol".into(),
            score,
            reason: reason.into(),
        }
    }
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct FindingItem {
    pub topic: PythonText,
    pub content: PythonText,
    pub tags: Vec<PythonText>,
    pub score: f64,
    pub reason: PythonText,
}
#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct RankResult {
    pub files: Vec<RankedItem>,
    pub symbols: Vec<RankedItem>,
    pub findings: Vec<FindingItem>,
}
impl RankResult {
    pub fn empty(&self) -> bool {
        self.files.is_empty() && self.symbols.is_empty() && self.findings.is_empty()
    }
    pub fn top_score(&self) -> f64 {
        self.files
            .iter()
            .chain(&self.symbols)
            .map(|i| i.score)
            .chain(self.findings.iter().map(|i| i.score))
            .fold(0f64, f64::max)
    }
}
pub(crate) fn sort_items(items: &mut [RankedItem]) {
    items.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.target.codepoints().cmp(b.target.codepoints()))
    });
}
pub(crate) fn sort_findings(items: &mut [FindingItem]) {
    items.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.topic.codepoints().cmp(b.topic.codepoints()))
    });
}
#[derive(Clone, Copy, Debug, Default, Serialize, Deserialize)]
pub struct Clock {
    pub now_ms: i64,
    pub now_ns: i64,
}
#[derive(Clone, Debug)]
pub struct RankRequest {
    pub agent_id: String,
    pub current_iteration: i64,
    pub prompt: PythonText,
    pub prompt_embedding: Vec<f32>,
    pub top_files: i64,
    pub top_symbols: i64,
    pub top_findings: i64,
    pub project_root: Option<PathBuf>,
    pub include_reactive: bool,
    pub clock: Clock,
}
impl Default for RankRequest {
    fn default() -> Self {
        Self {
            agent_id: String::new(),
            current_iteration: 0,
            prompt: "".into(),
            prompt_embedding: Vec::new(),
            top_files: 8,
            top_symbols: 5,
            top_findings: 3,
            project_root: None,
            include_reactive: true,
            clock: Clock::default(),
        }
    }
}
pub struct VectorScores {
    pub kept: Vec<usize>,
    pub scores: Vec<f32>,
}
pub struct LiveScores {
    pub slots: Vec<i64>,
    pub scores: Vec<f32>,
}
/// The provider owns dtype, reductions, stored-space dispatch and partition ties.
/// The ranker owns threshold/cap policy and checks returned row identities.
pub trait ContextNumerics {
    fn normalize_query(&mut self, query: &[f32]) -> Result<Vec<f32>>;
    fn rank_inline(&mut self, query: &[f32], blobs: &[Vec<u8>]) -> Result<VectorScores>;
    fn live_scores(
        &mut self,
        conn: &Connection,
        root: Option<&Path>,
        space: &str,
        query: &[f32],
    ) -> Result<Option<LiveScores>>;
    fn adaptive_threshold(&mut self, scores: &[f32], fixed: f64, enabled: bool) -> Result<f64>;
    fn capped_indices(
        &mut self,
        scores: &[f32],
        threshold: f64,
        headroom: f64,
        cap: usize,
    ) -> Result<Vec<usize>>;
}
#[derive(Clone, Debug, Serialize)]
pub struct ExplanationItem {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target: Option<PythonText>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub topic: Option<PythonText>,
    pub score: f64,
    pub reason: PythonText,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tags: Option<Vec<PythonText>>,
}
#[derive(Clone, Debug, Serialize)]
pub struct Score {
    pub target: PythonText,
    pub score: f64,
}
#[derive(Clone, Debug, Serialize)]
pub struct Change {
    pub target: PythonText,
    pub before: Option<f64>,
    pub after: Option<f64>,
    pub delta: Option<f64>,
}
#[derive(Clone, Debug, Serialize)]
pub struct ConfidenceGate {
    pub threshold: f64,
    pub suppressed: bool,
}
#[derive(Clone, Debug, Serialize)]
pub struct Explanation {
    pub prompt: PythonText,
    pub channels: BTreeMap<String, Vec<ExplanationItem>>,
    pub merge_before_boosts: Vec<Score>,
    pub boosts: BTreeMap<String, Vec<Change>>,
    pub confidence_gate: ConfidenceGate,
    pub candidates_before_gate: Vec<ExplanationItem>,
    pub final_files: Vec<ExplanationItem>,
    pub final_symbols: Vec<ExplanationItem>,
    pub final_findings: Vec<ExplanationItem>,
}
