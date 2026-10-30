//! Session context ranking with explicit policy, vector arithmetic and clocks.
mod boosts;
mod brief;
pub mod channels;
mod merge;
mod model;
mod numerics;
mod pipeline;
mod policy;
mod ppr;
mod render;
mod snapshot;
mod text;
pub use brief::{BriefOptions, build_session_brief};
pub use model::*;
pub use numerics::NativeNumerics;
pub use pipeline::{explain, rank};
pub use policy::{FusionMode, Policy, PprMode};
pub use render::{RenderOptions, render_block, visible_file_paths};
pub use snapshot::snapshot_session_scores;
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("{0}")]
    Invalid(String),
    #[error(transparent)]
    Sql(#[from] rusqlite::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Store(#[from] ken_store::StoreError),
    #[error(transparent)]
    Retrieval(#[from] ken_retrieval::RetrievalError),
    #[error(transparent)]
    Knowledge(#[from] ken_knowledge::Error),
    #[error(transparent)]
    Io(#[from] std::io::Error),
}
pub type Result<T> = std::result::Result<T, Error>;
pub(crate) fn prefix(len: usize, limit: i64) -> usize {
    if limit < 0 {
        len.saturating_sub(limit.unsigned_abs().try_into().unwrap_or(usize::MAX))
    } else {
        len.min(limit.try_into().unwrap_or(usize::MAX))
    }
}
pub(crate) fn rounded(value: f64, digits: usize) -> f64 {
    format!("{value:.digits$}").parse().unwrap_or(value)
}
