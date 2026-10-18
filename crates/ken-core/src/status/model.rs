use serde::Serialize;
use serde_json::{Map, Value};
use std::path::PathBuf;

#[derive(Debug)]
pub enum StatusReport {
    MissingProject { error: String },
    MetadataOnly(ProjectStatus),
    Installed(Box<InstalledStatus>),
}
#[derive(Debug, Serialize)]
pub struct ProjectStatus {
    pub project_root: PathBuf,
    pub project_id: Value,
    pub db: DatabaseStatus,
}
#[derive(Debug, Serialize)]
pub struct DatabaseStatus {
    pub path: PathBuf,
    pub exists: bool,
    pub size: String,
}
#[derive(Debug, Serialize)]
pub struct InstalledStatus {
    #[serde(flatten)]
    pub project: ProjectStatus,
    pub counts: StatusCounts,
    pub index_health: IndexHealth,
    pub rank_signals: RankSignals,
    pub embedding_coverage: EmbeddingCoverage,
    pub recommendations: Vec<String>,
    pub daemon: Map<String, Value>,
}
#[derive(Debug, Default, PartialEq, Eq, Serialize)]
pub struct StatusCounts {
    pub files: u64,
    pub files_embedded: u64,
    pub symbols: u64,
    pub symbols_embedded: u64,
    pub sessions: u64,
    pub active_sessions: u64,
    pub contexts: u64,
    pub prompt_contexts: u64,
    pub prompt_contexts_embedded: u64,
    pub interactions: u64,
    pub session_scores: u64,
    pub findings: u64,
    pub findings_embedded: u64,
    pub intent_sources: u64,
    pub intent_sources_embedded: u64,
}
#[derive(Debug, Serialize)]
pub struct IndexHealth {
    pub stale_files: u64,
    pub sample: Vec<String>,
}
#[derive(Debug, Serialize)]
pub struct RankSignals {
    pub index: String,
    pub embeddings: String,
    pub predictive: String,
    pub findings: String,
}
#[derive(Debug, Serialize)]
pub struct EmbeddingCoverage {
    pub embedded: u64,
    pub total: u64,
    pub percent: f64,
}
