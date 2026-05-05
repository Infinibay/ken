//! `PdfAdapter` — PDFs via `pdf-extract`.
//!
//! Strategy:
//!
//! * Decode the PDF byte stream once via
//!   `pdf_extract::extract_text_by_pages_from_mem` so we get one `String`
//!   per page (instead of a single concatenated blob).
//! * **One chunk per page** with kind `PdfSection` and position
//!   `PageRange { page, char_start, char_end }`. Char offsets are within
//!   the page's text since byte offsets in the original PDF are not
//!   meaningful for the consumer (PDFs aren't reflowable text).
//! * If a page is bigger than `MAX_CHARS_PER_CHUNK`, sub-chunk it
//!   char-aligned and keep the same `page` number on each piece.
//!
//! # Why not concatenate to one big chunk
//!
//! Page boundaries are the most reliable structural signal a PDF carries —
//! treating them as chunk boundaries lets the ranker attribute hits to a
//! specific page (which is what users want to be sent back to in
//! "open at page N" affordances). For prose without page structure, the
//! sub-chunking still keeps individual chunk sizes embedder-friendly.
//!
//! # Limitations (acceptable for v1)
//!
//! * Scanned PDFs (image-only) extract no text — they need OCR. Out of
//!   scope; flagged in `docs/05-roadmap.md`.
//! * Complex multi-column layouts may interleave text blocks in unhelpful
//!   order. `pdf-extract` does its best; future work could swap in
//!   `pdfium-render` for layout-aware extraction.
//! * No automatic title/heading extraction — the PDF metadata `/Title`
//!   would be a future hook (pdf-extract doesn't expose it directly).

use crate::ingest::{
    ChunkDraft, ContentAdapter, DocumentDraft, EmbedRequest, EmbedTarget, IngestContext,
    IngestError, IngestOutput, IngestResult, MimeHint, RawDocument, SignalKind,
};
use crate::types::{
    Acl, ChunkKind, ChunkPosition, ContentKind, EdgeKind, MetadataMap,
};

pub struct PdfAdapter;

impl PdfAdapter {
    /// Cap on per-page chunk size. Pages bigger than this are sub-divided
    /// char-aligned, preserving the page number on every piece.
    pub const MAX_CHARS_PER_CHUNK: usize = 4000;
}

impl Default for PdfAdapter {
    fn default() -> Self {
        Self
    }
}

impl ContentAdapter for PdfAdapter {
    fn kind(&self) -> ContentKind {
        ContentKind::Pdf
    }

    fn accepts(&self, hint: &MimeHint) -> bool {
        if let Some(mime) = &hint.mime {
            if mime.starts_with("application/pdf") || mime.starts_with("application/x-pdf") {
                return true;
            }
        }
        if let Some(ext) = &hint.extension {
            if ext == "pdf" {
                return true;
            }
        }
        false
    }

    fn ingest(&self, raw: RawDocument, _ctx: &IngestContext) -> IngestResult<IngestOutput> {
        // pdf-extract 0.10 doesn't expose `extract_text_by_pages_from_mem`,
        // but its `PlainTextOutput` emits form-feed (U+000C) between pages.
        // Splitting the full-document text on form-feeds reproduces the
        // per-page slicing without needing a temp file.
        let full = pdf_extract::extract_text_from_mem(&raw.bytes)
            .map_err(|e| IngestError::Decode(format!("pdf parse: {e}")))?;
        let pages: Vec<String> = full.split('\u{000C}').map(|s| s.to_string()).collect();

        let content_hash = *blake3::hash(&raw.bytes).as_bytes();
        let mime = raw
            .mime_hint
            .clone()
            .unwrap_or_else(|| "application/pdf".to_string());

        let mut metadata = raw.hint_metadata.clone();
        if metadata.size_bytes.is_none() {
            metadata.size_bytes = Some(raw.bytes.len() as u64);
        }
        if metadata.word_count.is_none() {
            let total: usize = pages.iter().map(|p| p.split_whitespace().count()).sum();
            metadata.word_count = Some(total as u32);
        }

        let document = DocumentDraft {
            external_id: raw.external_id.clone(),
            kind: ContentKind::Pdf,
            mime,
            title: None,
            path_or_url: Some(raw.source_uri.clone()),
            content_hash,
            acl: Acl::default(),
            metadata,
            source_modified_at: raw.source_modified_at,
        };

        let chunks_and_requests = chunk_pages(&pages, Self::MAX_CHARS_PER_CHUNK);
        let mut chunks = Vec::with_capacity(chunks_and_requests.len());
        let mut embed_requests = Vec::with_capacity(chunks_and_requests.len());
        for piece in chunks_and_requests {
            let idx = chunks.len();
            chunks.push(ChunkDraft {
                kind: ChunkKind::PdfSection,
                position: ChunkPosition::PageRange {
                    page: piece.page,
                    char_start: piece.char_start,
                    char_end: piece.char_end,
                },
                text: piece.text.clone(),
                metadata: MetadataMap {
                    word_count: Some(piece.text.split_whitespace().count() as u32),
                    tags: vec![format!("page:{}", piece.page)],
                    ..Default::default()
                },
            });
            embed_requests.push(EmbedRequest {
                target: EmbedTarget::Chunk(idx),
                text: piece.text,
            });
        }

        Ok(IngestOutput {
            document,
            chunks,
            entities: Vec::new(),
            edges: Vec::new(),
            embed_requests,
        })
    }

    fn ranking_signals(&self) -> &'static [SignalKind] {
        &[SignalKind::CosineThreshold(0.40), SignalKind::ZScoreNormalize]
    }

    fn relation_kinds(&self) -> &'static [EdgeKind] {
        &[]
    }
}

// ============================================================================
// Pure chunking helper (testable without a real PDF)
// ============================================================================

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct PagePiece {
    pub page: u32,
    pub char_start: u32,
    pub char_end: u32,
    pub text: String,
}

/// Split each page into one or more `PagePiece`s. Empty / whitespace-only
/// pages are dropped. A page over `max_chars` is divided char-aligned
/// keeping the same `page` number on each piece; `char_start`/`char_end`
/// are within the page's own text (not the document).
pub(crate) fn chunk_pages(pages: &[String], max_chars: usize) -> Vec<PagePiece> {
    let mut out = Vec::new();
    for (i, page) in pages.iter().enumerate() {
        let trimmed = page.trim();
        if trimmed.is_empty() {
            continue;
        }
        let page_no = (i + 1) as u32; // 1-indexed pages match user expectation.
        let total_chars = page.chars().count();
        if total_chars <= max_chars {
            out.push(PagePiece {
                page: page_no,
                char_start: 0,
                char_end: total_chars as u32,
                text: page.to_string(),
            });
            continue;
        }
        let mut buf = String::new();
        let mut count = 0u32;
        let mut piece_start = 0u32;
        for ch in page.chars() {
            buf.push(ch);
            count += 1;
            if count as usize >= max_chars {
                let piece_end = piece_start + count;
                out.push(PagePiece {
                    page: page_no,
                    char_start: piece_start,
                    char_end: piece_end,
                    text: std::mem::take(&mut buf),
                });
                piece_start = piece_end;
                count = 0;
            }
        }
        if !buf.is_empty() {
            let piece_end = piece_start + count;
            out.push(PagePiece {
                page: page_no,
                char_start: piece_start,
                char_end: piece_end,
                text: buf,
            });
        }
    }
    out
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    fn page(text: &str) -> String {
        text.to_string()
    }

    #[test]
    fn accepts_pdf_mime_and_extension() {
        let a = PdfAdapter;
        assert!(a.accepts(&MimeHint::from_mime("application/pdf")));
        assert!(a.accepts(&MimeHint::from_mime("application/x-pdf")));
        assert!(a.accepts(&MimeHint::from_uri("paper.pdf")));
        assert!(!a.accepts(&MimeHint::from_uri("page.html")));
        assert!(!a.accepts(&MimeHint::from_mime("text/plain")));
        assert!(!a.accepts(&MimeHint::default()));
    }

    #[test]
    fn relation_kinds_empty() {
        assert!(PdfAdapter.relation_kinds().is_empty());
    }

    #[test]
    fn chunk_pages_one_page_under_limit() {
        let pages = vec![page("Hello world.")];
        let pieces = chunk_pages(&pages, 100);
        assert_eq!(pieces.len(), 1);
        assert_eq!(pieces[0].page, 1);
        assert_eq!(pieces[0].char_start, 0);
        assert_eq!(pieces[0].char_end, 12);
        assert_eq!(pieces[0].text, "Hello world.");
    }

    #[test]
    fn chunk_pages_skips_empty_and_whitespace() {
        let pages = vec![page("Hello"), page("   \n  "), page(""), page("World")];
        let pieces = chunk_pages(&pages, 100);
        assert_eq!(pieces.len(), 2);
        // Page numbers preserve the *original* index (1-based), so empty
        // pages 2 and 3 are gone but page 4 stays page 4.
        assert_eq!(pieces[0].page, 1);
        assert_eq!(pieces[1].page, 4);
    }

    #[test]
    fn chunk_pages_subdivides_oversize_with_same_page_no() {
        let big = "x".repeat(2500);
        let pages = vec![page(&big)];
        let pieces = chunk_pages(&pages, 1000);
        assert_eq!(pieces.len(), 3, "expected 3 sub-chunks, got {pieces:?}");
        for p in &pieces {
            assert_eq!(p.page, 1);
        }
        assert_eq!(pieces[0].char_start, 0);
        assert_eq!(pieces[0].char_end, 1000);
        assert_eq!(pieces[1].char_start, 1000);
        assert_eq!(pieces[1].char_end, 2000);
        assert_eq!(pieces[2].char_start, 2000);
        assert_eq!(pieces[2].char_end, 2500);
        // Concatenating the pieces reproduces the original page text.
        let recombined: String = pieces.iter().map(|p| p.text.clone()).collect();
        assert_eq!(recombined, big);
    }

    #[test]
    fn chunk_pages_handles_unicode_chars() {
        // "café日本" has 6 chars (mix of 2-byte and 3-byte UTF-8) — at
        // max_chars=2 we get 3 pieces ("ca", "fé", "日本"). The point is
        // that we count CHARACTERS, not bytes, so chunks slice cleanly.
        let pages = vec![page("café日本")];
        let pieces = chunk_pages(&pages, 2);
        assert_eq!(pieces.len(), 3);
        assert_eq!(pieces[0].text, "ca");
        assert_eq!(pieces[1].text, "fé");
        assert_eq!(pieces[2].text, "日本");
        assert_eq!(pieces[0].char_end, 2);
        assert_eq!(pieces[1].char_start, 2);
        assert_eq!(pieces[2].char_start, 4);
        assert_eq!(pieces[2].char_end, 6);
    }
}
