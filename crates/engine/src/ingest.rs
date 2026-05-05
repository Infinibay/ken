use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::types::*;

// ============================================================================
// Errors
// ============================================================================

#[derive(Debug, Error)]
pub enum IngestError {
    #[error("decode failed: {0}")]
    Decode(String),
    #[error("unsupported content: {0}")]
    Unsupported(String),
    #[error("invalid input: {0}")]
    Invalid(String),
}

pub type IngestResult<T> = Result<T, IngestError>;

// ============================================================================
// Inputs
// ============================================================================

#[derive(Debug, Clone)]
pub struct RawDocument {
    pub bytes: Vec<u8>,
    pub source_uri: String,
    pub mime_hint: Option<String>,
    pub external_id: Option<String>,
    pub hint_metadata: MetadataMap,
    pub source_modified_at: Option<Timestamp>,
}

#[derive(Debug, Clone, Default)]
pub struct MimeHint {
    pub mime: Option<String>,
    pub extension: Option<String>,
}

impl MimeHint {
    pub fn from_uri(uri: &str) -> Self {
        let extension = uri
            .rsplit_once('.')
            .map(|(_, ext)| ext.to_ascii_lowercase());
        Self { mime: None, extension }
    }

    pub fn from_mime(mime: impl Into<String>) -> Self {
        Self { mime: Some(mime.into()), extension: None }
    }
}

#[derive(Debug, Clone)]
pub struct IngestContext {
    pub workspace_id: WorkspaceId,
    pub source_id: SourceId,
}

// ============================================================================
// Drafts (no IDs yet — orchestrator assigns when persisting)
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentDraft {
    pub external_id: Option<String>,
    pub kind: ContentKind,
    pub mime: String,
    pub title: Option<String>,
    pub path_or_url: Option<String>,
    pub content_hash: [u8; 32],
    pub acl: Acl,
    pub metadata: MetadataMap,
    pub source_modified_at: Option<Timestamp>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChunkDraft {
    pub kind: ChunkKind,
    pub position: ChunkPosition,
    pub text: String,
    pub metadata: MetadataMap,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EntityDraft {
    pub kind: EntityKind,
    pub canonical_name: String,
    pub aliases: Vec<String>,
    pub metadata: MetadataMap,
}

/// Endpoint of an `EdgeDraft`. Adapters reference local chunks/entities by
/// their index in the corresponding `IngestOutput` Vec; the orchestrator
/// resolves these to real `NodeRef`s when persisting.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EdgeEndpoint {
    /// The Document itself being ingested.
    Document,
    /// Index into `IngestOutput.chunks`.
    LocalChunk(usize),
    /// Index into `IngestOutput.entities`.
    LocalEntity(usize),
    /// Already-known node in the workspace.
    Known(NodeRef),
    /// External URI not yet ingested (late-binding when target is added).
    External(String),
}

#[derive(Debug, Clone)]
pub struct EdgeDraft {
    pub from: EdgeEndpoint,
    pub to: EdgeEndpoint,
    pub kind: EdgeKind,
    pub weight: f32,
    pub metadata: MetadataMap,
    pub created_by: EdgeOrigin,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EmbedTarget {
    /// Index into `IngestOutput.chunks`.
    Chunk(usize),
    /// Index into `IngestOutput.entities`.
    Entity(usize),
}

#[derive(Debug, Clone)]
pub struct EmbedRequest {
    pub target: EmbedTarget,
    pub text: String,
}

#[derive(Debug, Clone)]
pub struct IngestOutput {
    pub document: DocumentDraft,
    pub chunks: Vec<ChunkDraft>,
    pub entities: Vec<EntityDraft>,
    pub edges: Vec<EdgeDraft>,
    pub embed_requests: Vec<EmbedRequest>,
}

// ============================================================================
// Ranking signal hints (per-adapter)
// ============================================================================

/// How the ranker should treat scores produced for this adapter's content.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum SignalKind {
    /// Minimum cosine for this kind to register a semantic match.
    CosineThreshold(f32),
    /// Z-score normalize within this kind before cross-kind ranking.
    ZScoreNormalize,
    /// Use raw scores (no normalization).
    AbsoluteScale,
}

// ============================================================================
// ContentAdapter trait
// ============================================================================

/// One mini-engine per content type. See `docs/01-architecture.md`.
///
/// Adapters are pure: given a `RawDocument`, they produce an `IngestOutput`
/// of drafts. The engine orchestrator persists them, computes embeddings via
/// its global `Embedder`, and resolves cross-doc edges. Adapters never write
/// to storage and never call the embedder themselves.
pub trait ContentAdapter: Send + Sync {
    fn kind(&self) -> ContentKind;
    fn accepts(&self, hint: &MimeHint) -> bool;
    fn ingest(&self, raw: RawDocument, ctx: &IngestContext) -> IngestResult<IngestOutput>;
    fn ranking_signals(&self) -> &'static [SignalKind];
    fn relation_kinds(&self) -> &'static [EdgeKind];
}

/// All adapters the engine ships out of the box, ordered by specificity:
/// Code (when compiled in) and Markdown are checked before PlainText so a
/// `.rs` or `.md` file isn't silently captured by the more permissive
/// plain-text matcher.
///
/// Callers may build their own ordered slice if they have custom adapters;
/// `pick_adapter` walks the slice and picks the first one whose `accepts`
/// returns true.
pub fn default_adapters() -> Vec<Box<dyn ContentAdapter>> {
    let mut adapters: Vec<Box<dyn ContentAdapter>> = Vec::new();
    #[cfg(feature = "code")]
    adapters.push(Box::new(crate::ingest_code::CodeAdapter));
    #[cfg(feature = "pdf")]
    adapters.push(Box::new(crate::ingest_pdf::PdfAdapter));
    adapters.push(Box::new(crate::ingest_md::MarkdownAdapter));
    adapters.push(Box::new(PlainTextAdapter));
    adapters
}

pub fn pick_adapter<'a>(
    adapters: &'a [Box<dyn ContentAdapter>],
    hint: &MimeHint,
) -> Option<&'a dyn ContentAdapter> {
    adapters.iter().find(|a| a.accepts(hint)).map(|a| a.as_ref())
}

// ============================================================================
// PlainTextAdapter
// ============================================================================

pub struct PlainTextAdapter;

impl PlainTextAdapter {
    pub const MAX_CHARS_PER_CHUNK: usize = 4000;
    pub const MIN_CHARS_PER_CHUNK: usize = 1;
}

impl Default for PlainTextAdapter {
    fn default() -> Self {
        Self
    }
}

impl ContentAdapter for PlainTextAdapter {
    fn kind(&self) -> ContentKind {
        ContentKind::PlainText
    }

    fn accepts(&self, hint: &MimeHint) -> bool {
        if let Some(mime) = &hint.mime {
            if mime.starts_with("text/plain") {
                return true;
            }
        }
        if let Some(ext) = &hint.extension {
            if matches!(ext.as_str(), "txt" | "text" | "log") {
                return true;
            }
        }
        hint.mime.is_none() && hint.extension.is_none()
    }

    fn ingest(&self, raw: RawDocument, _ctx: &IngestContext) -> IngestResult<IngestOutput> {
        let text = std::str::from_utf8(&raw.bytes)
            .map_err(|e| IngestError::Decode(format!("invalid utf-8: {e}")))?;
        let content_hash = *blake3::hash(text.as_bytes()).as_bytes();
        let mime = raw.mime_hint.clone().unwrap_or_else(|| "text/plain".to_string());

        let mut metadata = raw.hint_metadata.clone();
        if metadata.size_bytes.is_none() {
            metadata.size_bytes = Some(raw.bytes.len() as u64);
        }
        if metadata.word_count.is_none() {
            metadata.word_count = Some(text.split_whitespace().count() as u32);
        }

        let document = DocumentDraft {
            external_id: raw.external_id.clone(),
            kind: ContentKind::PlainText,
            mime,
            title: None,
            path_or_url: Some(raw.source_uri.clone()),
            content_hash,
            acl: Acl::default(),
            metadata,
            source_modified_at: raw.source_modified_at,
        };

        let mut chunks: Vec<ChunkDraft> = Vec::new();
        let mut embed_requests: Vec<EmbedRequest> = Vec::new();

        for (start, end, body) in split_paragraphs(text) {
            for (sub_start, sub_end, sub_text) in
                split_oversize(start, end, body, Self::MAX_CHARS_PER_CHUNK)
            {
                if sub_text.trim().chars().count() < Self::MIN_CHARS_PER_CHUNK {
                    continue;
                }
                let idx = chunks.len();
                let word_count = sub_text.split_whitespace().count() as u32;
                chunks.push(ChunkDraft {
                    kind: ChunkKind::Paragraph,
                    position: ChunkPosition::ByteRange { start: sub_start, end: sub_end },
                    text: sub_text.to_string(),
                    metadata: MetadataMap {
                        word_count: Some(word_count),
                        ..Default::default()
                    },
                });
                embed_requests.push(EmbedRequest {
                    target: EmbedTarget::Chunk(idx),
                    text: sub_text.to_string(),
                });
            }
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
// Paragraph splitter
// ============================================================================

/// Split text into paragraph spans separated by blank lines. Tolerant of
/// `\r\n` and whitespace-only "blank" lines. Returns (byte_start, byte_end,
/// borrowed slice).
fn split_paragraphs(text: &str) -> Vec<(u64, u64, &str)> {
    let bytes = text.as_bytes();
    let mut out: Vec<(u64, u64, &str)> = Vec::new();
    let mut start = 0usize;
    let mut i = 0usize;
    while i < bytes.len() {
        if let Some(end_sep) = blank_line_separator_at(bytes, i) {
            let para = &text[start..i];
            let trimmed = para.trim_end();
            if !trimmed.is_empty() {
                let new_end = start + trimmed.len();
                out.push((start as u64, new_end as u64, trimmed));
            }
            start = end_sep;
            i = end_sep;
        } else {
            i += 1;
        }
    }
    if start < bytes.len() {
        let para = &text[start..];
        let trimmed = para.trim_end();
        if !trimmed.is_empty() {
            let new_end = start + trimmed.len();
            out.push((start as u64, new_end as u64, trimmed));
        }
    }
    out
}

/// At byte position `i`, is there a blank-line separator? A blank-line
/// separator starts with `\n` and contains at least one more `\n`,
/// optionally interleaved with spaces / tabs / `\r`. Returns the index just
/// past the separator if matched.
fn blank_line_separator_at(s: &[u8], i: usize) -> Option<usize> {
    if s.get(i) != Some(&b'\n') {
        return None;
    }
    let mut j = i + 1;
    let mut found_second_nl = false;
    while j < s.len() {
        match s[j] {
            b'\n' => {
                found_second_nl = true;
                j += 1;
            }
            b' ' | b'\t' | b'\r' => {
                j += 1;
            }
            _ => break,
        }
    }
    if found_second_nl { Some(j) } else { None }
}

/// Split a paragraph that exceeds `max_chars` into char-aligned subchunks.
/// Returns sub-spans with corrected byte offsets relative to the original
/// document.
fn split_oversize<'a>(
    start: u64,
    end: u64,
    text: &'a str,
    max_chars: usize,
) -> Vec<(u64, u64, &'a str)> {
    if text.chars().count() <= max_chars {
        return vec![(start, end, text)];
    }
    let mut out = Vec::new();
    let mut char_count = 0usize;
    let mut window_start = 0usize;
    for (b, ch) in text.char_indices() {
        let byte_offset = b + ch.len_utf8();
        char_count += 1;
        if char_count >= max_chars {
            let sub = &text[window_start..byte_offset];
            out.push((start + window_start as u64, start + byte_offset as u64, sub));
            window_start = byte_offset;
            char_count = 0;
        }
    }
    if window_start < text.len() {
        let sub = &text[window_start..];
        out.push((start + window_start as u64, end, sub));
    }
    out
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    fn ctx() -> IngestContext {
        IngestContext { workspace_id: WorkspaceId(1), source_id: SourceId(1) }
    }

    fn raw(text: &str, uri: &str) -> RawDocument {
        RawDocument {
            bytes: text.as_bytes().to_vec(),
            source_uri: uri.to_string(),
            mime_hint: Some("text/plain".to_string()),
            external_id: Some(uri.to_string()),
            hint_metadata: MetadataMap::default(),
            source_modified_at: None,
        }
    }

    #[test]
    fn accepts_text_mime() {
        let a = PlainTextAdapter;
        assert!(a.accepts(&MimeHint::from_mime("text/plain; charset=utf-8")));
        assert!(a.accepts(&MimeHint::from_mime("text/plain")));
        assert!(a.accepts(&MimeHint::from_uri("notes.txt")));
        assert!(a.accepts(&MimeHint::from_uri("server.log")));
        assert!(a.accepts(&MimeHint::default()));
        assert!(!a.accepts(&MimeHint::from_mime("application/pdf")));
        assert!(!a.accepts(&MimeHint::from_uri("foo.pdf")));
    }

    #[test]
    fn ingest_empty_input_no_chunks() {
        let a = PlainTextAdapter;
        let out = a.ingest(raw("", "empty.txt"), &ctx()).unwrap();
        assert!(out.chunks.is_empty());
        assert!(out.embed_requests.is_empty());
        assert_eq!(out.document.kind, ContentKind::PlainText);
    }

    #[test]
    fn ingest_whitespace_only_no_chunks() {
        let a = PlainTextAdapter;
        let out = a.ingest(raw("   \n\n  \n\n   ", "ws.txt"), &ctx()).unwrap();
        assert!(out.chunks.is_empty());
    }

    #[test]
    fn ingest_single_paragraph() {
        let a = PlainTextAdapter;
        let out = a.ingest(raw("hello world", "x.txt"), &ctx()).unwrap();
        assert_eq!(out.chunks.len(), 1);
        assert_eq!(out.chunks[0].text, "hello world");
        assert!(matches!(
            out.chunks[0].position,
            ChunkPosition::ByteRange { start: 0, end: 11 }
        ));
        assert_eq!(out.embed_requests.len(), 1);
        assert_eq!(out.embed_requests[0].target, EmbedTarget::Chunk(0));
    }

    #[test]
    fn ingest_multiple_paragraphs() {
        let a = PlainTextAdapter;
        let text = "first paragraph\n\nsecond paragraph\n\nthird";
        let out = a.ingest(raw(text, "x.txt"), &ctx()).unwrap();
        assert_eq!(out.chunks.len(), 3);
        assert_eq!(out.chunks[0].text, "first paragraph");
        assert_eq!(out.chunks[1].text, "second paragraph");
        assert_eq!(out.chunks[2].text, "third");
    }

    #[test]
    fn ingest_handles_crlf_paragraph_breaks() {
        let a = PlainTextAdapter;
        let text = "alpha\r\n\r\nbeta\r\n\r\ngamma";
        let out = a.ingest(raw(text, "x.txt"), &ctx()).unwrap();
        assert_eq!(out.chunks.len(), 3);
        assert_eq!(out.chunks[0].text, "alpha");
        assert_eq!(out.chunks[1].text, "beta");
        assert_eq!(out.chunks[2].text, "gamma");
    }

    #[test]
    fn ingest_handles_extra_newlines() {
        let a = PlainTextAdapter;
        let text = "a\n\n\n\n\nb";
        let out = a.ingest(raw(text, "x.txt"), &ctx()).unwrap();
        assert_eq!(out.chunks.len(), 2);
        assert_eq!(out.chunks[0].text, "a");
        assert_eq!(out.chunks[1].text, "b");
    }

    #[test]
    fn ingest_preserves_byte_positions() {
        let a = PlainTextAdapter;
        let text = "first\n\nsecond";
        let out = a.ingest(raw(text, "x.txt"), &ctx()).unwrap();
        match out.chunks[0].position {
            ChunkPosition::ByteRange { start, end } => {
                assert_eq!(start, 0);
                assert_eq!(end, 5);
                assert_eq!(&text[start as usize..end as usize], "first");
            }
            _ => panic!("expected byte range"),
        }
        match out.chunks[1].position {
            ChunkPosition::ByteRange { start, end } => {
                assert_eq!(start, 7);
                assert_eq!(end, 13);
                assert_eq!(&text[start as usize..end as usize], "second");
            }
            _ => panic!("expected byte range"),
        }
    }

    #[test]
    fn embed_requests_align_with_chunks() {
        let a = PlainTextAdapter;
        let out = a
            .ingest(raw("p1\n\np2\n\np3", "x.txt"), &ctx())
            .unwrap();
        assert_eq!(out.embed_requests.len(), out.chunks.len());
        for (i, req) in out.embed_requests.iter().enumerate() {
            assert_eq!(req.target, EmbedTarget::Chunk(i));
            assert_eq!(req.text, out.chunks[i].text);
        }
    }

    #[test]
    fn content_hash_is_blake3_of_text() {
        let a = PlainTextAdapter;
        let text = "deterministic input";
        let out = a.ingest(raw(text, "x.txt"), &ctx()).unwrap();
        assert_eq!(out.document.content_hash, *blake3::hash(text.as_bytes()).as_bytes());
        let out2 = a.ingest(raw(text, "x.txt"), &ctx()).unwrap();
        assert_eq!(out.document.content_hash, out2.document.content_hash);
    }

    #[test]
    fn invalid_utf8_returns_decode_error() {
        let a = PlainTextAdapter;
        let bad = vec![0xC3, 0x28];
        let r = RawDocument {
            bytes: bad,
            source_uri: "bad.bin".into(),
            mime_hint: None,
            external_id: None,
            hint_metadata: MetadataMap::default(),
            source_modified_at: None,
        };
        let res = a.ingest(r, &ctx());
        assert!(matches!(res, Err(IngestError::Decode(_))));
    }

    #[test]
    fn oversize_paragraph_is_split() {
        let a = PlainTextAdapter;
        let big = "x".repeat(PlainTextAdapter::MAX_CHARS_PER_CHUNK + 500);
        let out = a.ingest(raw(&big, "big.txt"), &ctx()).unwrap();
        assert!(out.chunks.len() >= 2);
        let total: usize = out.chunks.iter().map(|c| c.text.chars().count()).sum();
        assert_eq!(total, big.chars().count());
    }

    #[test]
    fn ranking_signals_and_relation_kinds() {
        let a = PlainTextAdapter;
        let signals = a.ranking_signals();
        assert!(signals.iter().any(|s| matches!(s, SignalKind::CosineThreshold(_))));
        assert!(a.relation_kinds().is_empty());
    }

    #[test]
    fn metadata_word_count_filled() {
        let a = PlainTextAdapter;
        let out = a.ingest(raw("one two three", "x.txt"), &ctx()).unwrap();
        assert_eq!(out.document.metadata.word_count, Some(3));
        assert_eq!(out.chunks[0].metadata.word_count, Some(3));
    }

    #[test]
    fn split_paragraphs_unicode_safe() {
        let text = "café\n\nñoño\n\n日本語";
        let out = split_paragraphs(text);
        assert_eq!(out.len(), 3);
        assert_eq!(out[0].2, "café");
        assert_eq!(out[1].2, "ñoño");
        assert_eq!(out[2].2, "日本語");
    }
}
