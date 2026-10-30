//! Two exploration concepts: raw syntax evaluation and semantic catalog buckets.
pub mod buckets;
mod cache;
mod syntax;
use super::search::SearchOptions;
pub use syntax::{ExplorationError, ExplorationOptions, SyntaxExploration};
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum PatternBackend {
    #[default]
    Exploration,
    Indexed,
}
#[derive(Clone, Default)]
pub struct PatternOptions {
    pub search: SearchOptions,
    pub backend: PatternBackend,
    pub profile: bool,
}
