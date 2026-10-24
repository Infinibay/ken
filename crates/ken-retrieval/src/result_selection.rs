//! Ranked owners that occupy result slots before any character-budget trimming.
use crate::query::{CodeMatch, SearchRequest};
use std::collections::BTreeSet;
pub fn displayed_matches<'a>(
    matches: &'a [CodeMatch],
    request: &SearchRequest,
) -> impl Iterator<Item = (usize, &'a CodeMatch)> {
    let files = request.target() == "file";
    let mut seen = BTreeSet::new();
    matches
        .iter()
        .enumerate()
        .filter(move |(_, m)| !files || seen.insert(m.entity.path.as_str()))
        .take(request.limit())
}
