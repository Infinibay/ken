//! Symbol-level diff resolution (Phase 1.5). For a file's diff hunks
//! plus the post-state blob content, returns the qualified names of the
//! enclosing code symbols. Composes with the existing `ingest_code`
//! adapter — same tree-sitter walkers, same per-language conventions
//! (`User::validate` for Rust, `User.validate` for Python, etc).
//!
//! All ranges are line-based (1-indexed, inclusive), matching both
//! libgit2's `DiffHunk` and the `Symbol { line_start, line_end }` we get
//! from `ingest_code::extract_symbols`. No byte-offset accounting needed.
//!
//! The qualified names returned by this module are intended to compose
//! with the `git+symbol:<workspace>:<path>:<qualified_name>` external-URI
//! convention used by `EdgeKind::ChangesSymbol`. The persistence layer
//! does the URI assembly.

use ahash::AHashSet;

use super::HunkRange;
use crate::ingest_code::{extract_symbols, CodeLanguage};

/// Slim version of `ingest_code::Symbol` cached per blob — drops the
/// `text` field (the source code) to keep memory bounded for repos with
/// thousands of files.
#[derive(Debug, Clone)]
pub struct CachedSymbol {
    pub qualified_name: String,
    pub line_start: u32,
    pub line_end: u32,
}

/// Parse the file at `path` (using extension-based language detection)
/// and return its full symbol table — every function / class / etc.
/// Empty when the language isn't recognized, the bytes aren't UTF-8, or
/// tree-sitter parsing fails.
pub fn parse_symbol_table(path: &str, file_bytes: &[u8]) -> Vec<CachedSymbol> {
    let Some(language) = CodeLanguage::detect_for_path(path) else {
        return Vec::new();
    };
    let Ok(text) = std::str::from_utf8(file_bytes) else {
        return Vec::new();
    };
    let extracted = match extract_symbols(language, text) {
        Ok(e) => e,
        Err(_) => return Vec::new(),
    };
    extracted
        .symbols
        .into_iter()
        .map(|s| CachedSymbol {
            qualified_name: s.qualified_name,
            line_start: s.line_start,
            line_end: s.line_end,
        })
        .collect()
}

/// For each hunk, return every symbol it touched (deduplicated across
/// all hunks). The matching rule has two cases:
///
/// * **Hunk fits inside a symbol** (`line_start ≤ hunk.lo && hunk.hi ≤
///   line_end`): pick the *smallest* containing symbol. This is the
///   "small change inside a function" case — we want the function, not
///   the enclosing impl/class.
/// * **Hunk spans multiple symbols** (overlaps but doesn't fit inside
///   any one): pick *every* symbol the hunk overlaps. This is the
///   "rewriting an entire impl block" case — every method in scope was
///   touched. If we collapsed to "smallest overlapping", we'd silently
///   drop methods at the cost of a span tie-break.
pub fn overlap_qnames(symbols: &[CachedSymbol], hunks: &[HunkRange]) -> Vec<String> {
    if symbols.is_empty() || hunks.is_empty() {
        return Vec::new();
    }
    let mut found: AHashSet<String> = AHashSet::new();
    for h in hunks {
        let (lo, hi) = if h.new_lines == 0 {
            // Pure deletion at post-state line `new_start` — anchor on
            // that single line so we still locate the enclosing symbol.
            (h.new_start, h.new_start)
        } else {
            (h.new_start, h.new_start + h.new_lines - 1)
        };
        match best_for_hunk(symbols, lo, hi) {
            HunkMatch::Inside(name) => {
                found.insert(name);
            }
            HunkMatch::Spanning(names) => {
                found.extend(names);
            }
            HunkMatch::None => {}
        }
    }
    found.into_iter().collect()
}

/// One-shot convenience wrapper used by unit tests and any callers that
/// don't need the cache. Production code should go through the walker's
/// `SymbolCache` to amortize parse cost across commits.
pub fn resolve_hunk_symbols(
    path: &str,
    file_bytes: &[u8],
    hunks: &[HunkRange],
) -> Vec<String> {
    overlap_qnames(&parse_symbol_table(path, file_bytes), hunks)
}

enum HunkMatch {
    /// Hunk fits inside the (smallest) named symbol.
    Inside(String),
    /// Hunk spans multiple symbols; every named symbol was touched.
    Spanning(Vec<String>),
    /// Hunk doesn't overlap any symbol (e.g., pure top-level `use` line).
    None,
}

fn best_for_hunk(symbols: &[CachedSymbol], lo: u32, hi: u32) -> HunkMatch {
    let mut smallest_containing: Option<(u32, &str)> = None;
    let mut spanning: Vec<&str> = Vec::new();
    for s in symbols {
        let span = s.line_end.saturating_sub(s.line_start).saturating_add(1);
        if s.line_start <= lo && hi <= s.line_end {
            // Hunk fits inside this symbol.
            if smallest_containing.is_none_or(|(prev, _)| span < prev) {
                smallest_containing = Some((span, s.qualified_name.as_str()));
            }
        } else if lo <= s.line_start && s.line_end <= hi {
            // Symbol fits inside the hunk (the "rewrote a whole impl"
            // case). Every such symbol was touched.
            spanning.push(s.qualified_name.as_str());
        }
    }
    if let Some((_, name)) = smallest_containing {
        HunkMatch::Inside(name.to_string())
    } else if !spanning.is_empty() {
        HunkMatch::Spanning(spanning.iter().map(|s| s.to_string()).collect())
    } else {
        HunkMatch::None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rust_fixture() -> &'static str {
        // Lines 1-4: imports/header; 5-12: User struct; 13-26: impl block
        // with two methods (validate around 14-19, name around 21-25).
        "\
//! User profile module.
use std::collections::HashMap;

pub struct User {
    pub id: u64,
    pub name: String,
    pub email: String,
    pub created_at: u64,
}

impl User {
    pub fn validate(&self) -> bool {
        if self.email.is_empty() {
            return false;
        }
        self.email.contains('@')
    }

    pub fn name(&self) -> &str {
        &self.name
    }
}
"
    }

    #[test]
    fn returns_empty_for_unknown_extension() {
        let out = resolve_hunk_symbols("foo.unknown", b"x", &[HunkRange { new_start: 1, new_lines: 1 }]);
        assert!(out.is_empty());
    }

    #[test]
    fn returns_empty_for_invalid_utf8() {
        let bytes = vec![0xff, 0xfe, 0xfd];
        let out = resolve_hunk_symbols("foo.rs", &bytes, &[HunkRange { new_start: 1, new_lines: 1 }]);
        assert!(out.is_empty());
    }

    #[test]
    fn picks_inner_method_for_a_hunk_inside_one() {
        let src = rust_fixture();
        // Hunk hits line 14 (inside `validate`).
        let names =
            resolve_hunk_symbols("src/user.rs", src.as_bytes(), &[HunkRange { new_start: 14, new_lines: 2 }]);
        assert!(names.iter().any(|n| n == "User::validate"), "got {names:?}");
        assert!(!names.iter().any(|n| n == "User::name"));
    }

    #[test]
    fn deduplicates_when_two_hunks_hit_the_same_symbol() {
        let src = rust_fixture();
        let names = resolve_hunk_symbols(
            "src/user.rs",
            src.as_bytes(),
            &[
                HunkRange { new_start: 14, new_lines: 1 },
                HunkRange { new_start: 16, new_lines: 1 },
            ],
        );
        assert_eq!(names.iter().filter(|n| n.as_str() == "User::validate").count(), 1);
    }

    #[test]
    fn handles_pure_deletion_hunk() {
        let src = rust_fixture();
        // new_lines = 0 → pure deletion at post-state line 14.
        let names =
            resolve_hunk_symbols("src/user.rs", src.as_bytes(), &[HunkRange { new_start: 14, new_lines: 0 }]);
        assert!(names.iter().any(|n| n == "User::validate"));
    }

    #[test]
    fn ignores_hunks_outside_any_symbol() {
        let src = rust_fixture();
        // Line 2 is a `use` statement at the top — outside every Symbol.
        let names =
            resolve_hunk_symbols("src/user.rs", src.as_bytes(), &[HunkRange { new_start: 2, new_lines: 1 }]);
        assert!(names.is_empty(), "got {names:?}");
    }

    #[test]
    fn parse_then_overlap_matches_oneshot() {
        // Equivalence: `resolve_hunk_symbols` and `overlap_qnames(parse_…)`
        // should agree. This is the property the cache relies on.
        let src = rust_fixture();
        let hunks = [HunkRange { new_start: 22, new_lines: 1 }];
        let one_shot = resolve_hunk_symbols("src/user.rs", src.as_bytes(), &hunks);
        let table = parse_symbol_table("src/user.rs", src.as_bytes());
        let two_step = overlap_qnames(&table, &hunks);
        assert_eq!(one_shot, two_step);
    }
}
