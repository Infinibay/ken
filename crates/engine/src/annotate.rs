//! Annotators — post-ingest passes that scan chunk text and emit edges
//! the adapter didn't (or couldn't) emit.
//!
//! The first annotator is the **URL extractor**: walks chunk text, finds
//! `http(s)://...` URLs, and emits `Chunk → External(url)` edges of kind
//! `References`. Adapter-emitted edges (e.g. Markdown's `[text](url)` →
//! `Document → External` `Cites`) live alongside these — they answer
//! different questions:
//!
//! * Adapter `Cites` (Document-level): "this document explicitly references
//!   this URL via formatted markup."
//! * Annotator `References` (Chunk-level): "this specific chunk mentions
//!   this URL in plain text — useful for span attribution and for catching
//!   URLs in non-markup content (plain text, code comments, PDF prose)."
//!
//! Both kinds dedup at storage layer via `add_edge` (workspace, from, to,
//! kind) → max(weight).
//!
//! # Why hand-rolled instead of `regex`?
//!
//! URL grammars in the wild are messy and standard regexes either over- or
//! under-match. A small, readable scanner that consumes RFC-3986 URL chars
//! and strips trailing punctuation hits the 95% case without dragging in a
//! direct `regex` dependency. When ticket-id / file-ref patterns land they
//! can keep the same shape.

use crate::storage::NewEdge;
use crate::types::{
    ChunkId, EdgeKind, EdgeOrigin, MetadataMap, NodeRef, WorkspaceId,
};

/// Extract `http://` and `https://` URLs from `text`. The scan is greedy
/// over RFC-3986 unreserved + reserved chars and trims trailing
/// sentence-terminating punctuation that is rarely part of a URL.
/// Duplicates are removed (first occurrence wins).
pub fn extract_urls(text: &str) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    let bytes = text.as_bytes();
    let mut i = 0usize;

    while i < bytes.len() {
        if let Some(end) = match_scheme(bytes, i) {
            // Scan forward consuming URL chars.
            let mut j = end;
            while j < bytes.len() && is_url_char(bytes[j]) {
                j += 1;
            }
            // Strip trailing punctuation that is almost always sentence-end.
            while j > end && is_trailing_strip(bytes[j - 1]) {
                j -= 1;
            }
            // Balance parens: if there are more `)` than `(`, drop trailing `)`s.
            // Common case: "see (https://example.com)" — scanner picks up the
            // closing paren we don't want.
            j = balance_parens(bytes, end, j);

            // Reject zero-length authority (e.g. bare `https://`).
            if j > end + 1 {
                let url = std::str::from_utf8(&bytes[i..j]).unwrap_or("").to_string();
                if !out.iter().any(|u| u == &url) {
                    out.push(url);
                }
                i = j;
                continue;
            }
        }
        i += 1;
    }

    out
}

/// Build edges for every URL found in every chunk's text.
pub fn url_edges_for_chunks(
    workspace_id: WorkspaceId,
    chunks: &[(ChunkId, String)],
) -> Vec<NewEdge> {
    let mut edges = Vec::new();
    for (cid, text) in chunks {
        for url in extract_urls(text) {
            edges.push(NewEdge {
                workspace_id,
                from: NodeRef::Chunk(*cid),
                to: NodeRef::External(url),
                kind: EdgeKind::References,
                weight: 1.0,
                metadata: MetadataMap::default(),
                created_by: EdgeOrigin::UrlResolver,
            });
        }
    }
    edges
}

// ============================================================================
// Internals
// ============================================================================

/// At byte offset `i`, return `Some(end_of_scheme)` if a known scheme starts
/// here (i.e. `http://` or `https://`). The scheme must be word-boundaried —
/// `xhttp://` doesn't count.
fn match_scheme(bytes: &[u8], i: usize) -> Option<usize> {
    if i > 0 {
        let prev = bytes[i - 1];
        if (prev as char).is_alphanumeric() || prev == b'_' {
            return None;
        }
    }
    if bytes[i..].starts_with(b"https://") {
        Some(i + 8)
    } else if bytes[i..].starts_with(b"http://") {
        Some(i + 7)
    } else {
        None
    }
}

fn is_url_char(b: u8) -> bool {
    matches!(
        b,
        b'A'..=b'Z'
        | b'a'..=b'z'
        | b'0'..=b'9'
        | b'-' | b'.' | b'_' | b'~'
        | b':' | b'/' | b'?' | b'#' | b'[' | b']' | b'@'
        | b'!' | b'$' | b'&' | b'\'' | b'(' | b')' | b'*' | b'+'
        | b',' | b';' | b'=' | b'%'
    )
}

fn is_trailing_strip(b: u8) -> bool {
    matches!(b, b'.' | b',' | b';' | b':' | b'!' | b'?' | b'"' | b'\'')
}

fn balance_parens(bytes: &[u8], start: usize, mut end: usize) -> usize {
    let mut opens = 0i32;
    let mut closes = 0i32;
    for &b in &bytes[start..end] {
        if b == b'(' {
            opens += 1;
        } else if b == b')' {
            closes += 1;
        }
    }
    while closes > opens && end > start {
        if bytes[end - 1] == b')' {
            end -= 1;
            closes -= 1;
        } else {
            break;
        }
    }
    end
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_simple_https_url() {
        assert_eq!(
            extract_urls("see https://anthropic.com for details"),
            vec!["https://anthropic.com"],
        );
    }

    #[test]
    fn extracts_http_and_paths() {
        assert_eq!(
            extract_urls("docs at http://example.com/docs/page?x=1#section"),
            vec!["http://example.com/docs/page?x=1#section"],
        );
    }

    #[test]
    fn strips_trailing_punctuation() {
        assert_eq!(
            extract_urls("visit https://example.com."),
            vec!["https://example.com"],
        );
        assert_eq!(
            extract_urls("read https://example.com/page, then continue"),
            vec!["https://example.com/page"],
        );
        assert_eq!(
            extract_urls("https://example.com?"),
            vec!["https://example.com"],
        );
    }

    #[test]
    fn balances_parens() {
        // Parenthesized: `(https://example.com)` — drop trailing `)`
        assert_eq!(
            extract_urls("see (https://example.com) for more"),
            vec!["https://example.com"],
        );
        // But a URL with internal parens is preserved:
        // `https://en.wikipedia.org/wiki/Rust_(programming_language)`
        assert_eq!(
            extract_urls("https://en.wikipedia.org/wiki/Rust_(programming_language)"),
            vec!["https://en.wikipedia.org/wiki/Rust_(programming_language)"],
        );
    }

    #[test]
    fn rejects_word_boundary_violations() {
        // `xhttps://...` is not a URL match.
        assert!(extract_urls("xhttps://example.com").is_empty());
        // `_http://` neither.
        assert!(extract_urls("_http://example.com").is_empty());
    }

    #[test]
    fn rejects_bare_scheme() {
        assert!(extract_urls("https://").is_empty());
        assert!(extract_urls("http://").is_empty());
    }

    #[test]
    fn finds_multiple_urls() {
        let urls = extract_urls(
            "first https://anthropic.com and then http://example.org/page",
        );
        assert_eq!(urls.len(), 2);
        assert!(urls.contains(&"https://anthropic.com".to_string()));
        assert!(urls.contains(&"http://example.org/page".to_string()));
    }

    #[test]
    fn dedupes_repeats() {
        let urls = extract_urls(
            "https://example.com is the same as https://example.com itself",
        );
        assert_eq!(urls, vec!["https://example.com"]);
    }

    #[test]
    fn url_edges_for_chunks_emits_chunk_to_external() {
        let chunks = vec![
            (ChunkId(7), "see https://anthropic.com".to_string()),
            (ChunkId(8), "no urls here".to_string()),
            (ChunkId(9), "two: http://a.com and https://b.com".to_string()),
        ];
        let edges = url_edges_for_chunks(WorkspaceId(1), &chunks);
        assert_eq!(edges.len(), 3);
        for e in &edges {
            assert_eq!(e.kind, EdgeKind::References);
            assert_eq!(e.created_by, EdgeOrigin::UrlResolver);
            assert_eq!(e.workspace_id, WorkspaceId(1));
            assert!(matches!(e.from, NodeRef::Chunk(_)));
            assert!(matches!(e.to, NodeRef::External(_)));
        }
        // Order preserved per chunk.
        assert!(matches!(&edges[0].from, NodeRef::Chunk(c) if c.0 == 7));
        assert!(matches!(&edges[1].from, NodeRef::Chunk(c) if c.0 == 9));
        assert!(matches!(&edges[2].from, NodeRef::Chunk(c) if c.0 == 9));
    }

    #[test]
    fn handles_unicode_text_around_urls() {
        let urls = extract_urls("café ☕ → https://example.com — fin");
        assert_eq!(urls, vec!["https://example.com"]);
    }
}
