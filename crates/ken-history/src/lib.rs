//! Historical evidence and lexical source relations. No model or daemon ownership.
pub mod clones;
pub mod cochange;
pub mod graphs;
pub mod intent;

use std::path::{Component, Path};

#[derive(Debug, thiserror::Error)]
pub enum HistoryError {
    #[error(transparent)]
    Database(#[from] rusqlite::Error),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error("{0}")]
    Invalid(String),
    #[error("native navigation: {0}")]
    Navigation(String),
}
pub type Result<T> = std::result::Result<T, HistoryError>;

// Pathlib normalization removes redundant separators and `.` components but
// preserves `..` and names such as `.hidden`.
pub(crate) fn normalize(path: &str) -> String {
    let parts: Vec<_> = Path::new(path)
        .components()
        .filter_map(|part| match part {
            Component::CurDir | Component::RootDir => None,
            other => Some(other.as_os_str().to_string_lossy()),
        })
        .collect();
    let mut value = parts.join("/");
    if path.starts_with('/') {
        value.insert(0, '/');
        if path.starts_with("//") && !path.starts_with("///") {
            value.insert(0, '/');
        }
    }
    if value.is_empty() { ".".into() } else { value }
}

pub(crate) fn project(root: &Path) -> Result<ken_core::project::ProjectPaths> {
    let context = ken_core::project::DiscoveryContext::from_process()
        .map_err(|e| HistoryError::Invalid(e.to_string()))?;
    ken_core::project::ProjectPaths::at(root, &context)
        .map_err(|e| HistoryError::Invalid(e.to_string()))
}

// Rust's decimal formatting rounds the original binary value to even, as
// Python round(x, n) does. Scaling then rounding would change halfway cases.
pub(crate) fn rounded(value: f64, digits: usize) -> f64 {
    format!("{value:.digits$}").parse().unwrap_or(value)
}

pub(crate) fn positive_limit(value: i64) -> usize {
    usize::try_from(value.max(1)).unwrap_or(usize::MAX)
}

/// Python's splitlines, including non-LF Unicode boundaries and CRLF.
pub(crate) fn source_lines(text: &str) -> Vec<&str> {
    let mut lines = Vec::new();
    let mut start = 0;
    let mut chars = text.char_indices().peekable();
    while let Some((offset, c)) = chars.next() {
        if matches!(
            c,
            '\n' | '\r' | '\u{b}' | '\u{c}' | '\u{1c}'
                ..='\u{1e}' | '\u{85}' | '\u{2028}' | '\u{2029}'
        ) {
            lines.push(&text[start..offset]);
            start = offset + c.len_utf8();
            if c == '\r' && chars.peek().is_some_and(|(_, next)| *next == '\n') {
                let (offset, c) = chars.next().expect("peeked LF");
                start = offset + c.len_utf8();
            }
        }
    }
    if start < text.len() {
        lines.push(&text[start..]);
    }
    lines
}
