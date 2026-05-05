//! Ranker — multi-channel relevance scoring.
//!
//! See `docs/03-ranking.md` for the algorithm. The ranker consumes the fixed
//! `EventType` vocabulary and returns a list of `RankItem` (target + score +
//! reason). Channels are independent and merged via per-target `max`, then
//! reactive↔predictive blend with a saturating alpha, then a confidence gate
//! and a MAD-based outlier filter.

pub mod merge;
pub mod stats;

#[cfg(feature = "postgres")]
pub mod predictive;
#[cfg(feature = "postgres")]
pub mod ranker;
#[cfg(feature = "postgres")]
pub mod reactive;
#[cfg(feature = "postgres")]
pub mod semantic;

#[cfg(feature = "postgres")]
pub use ranker::{RankRequest, RankResult, Ranker, RankerConfig};
