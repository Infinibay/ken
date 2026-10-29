//! Shared operation ownership, populated by the authoritative declaration collector.
use std::collections::{BTreeMap, BTreeSet};
#[derive(Default)]
pub(super) struct Ownership {
    pub nodes: BTreeMap<usize, String>,
    pub classes: BTreeMap<usize, String>,
    pub prototypes: BTreeSet<usize>,
    pub functions: BTreeSet<usize>,
}
