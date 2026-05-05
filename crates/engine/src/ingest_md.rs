//! `MarkdownAdapter` — `ContentAdapter` for CommonMark.
//!
//! Strategy:
//!
//! * Parse the source with `pulldown-cmark` and an offset iterator so every
//!   event carries its byte range in the original text.
//! * **Section** = the span between H1/H2 headings (lower-level headings
//!   stay inside the parent section). The first chunk's text starts at byte
//!   0, so a leading paragraph that precedes any heading is preserved.
//! * Each section becomes one `Chunk` with kind `Heading` if it begins with
//!   a heading, else `Paragraph`. Position is `ByteRange` over the original
//!   markdown bytes, so callers can render the source slice verbatim
//!   (including formatting). The chunk's `tags` carry `["h1"]` / `["h2"]`
//!   so the ranker can later weight them.
//! * Long sections are sub-chunked at `MAX_CHARS_PER_CHUNK` (same constant
//!   as `PlainTextAdapter`).
//! * Inline links (`[text](url)`) emit `EdgeDraft { kind: Cites }` with
//!   `from: Document, to: External(url)` so the engine learns the
//!   citation graph for free. The link text is preserved in
//!   `metadata.extra.link_text` for forensics.

use pulldown_cmark::{Event, HeadingLevel, Options, Parser, Tag, TagEnd};
use serde_json::json;

use crate::ingest::{
    ChunkDraft, ContentAdapter, DocumentDraft, EdgeDraft, EdgeEndpoint, EmbedRequest, EmbedTarget,
    IngestContext, IngestError, IngestOutput, IngestResult, MimeHint, RawDocument, SignalKind,
};
use crate::types::{
    Acl, ChunkKind, ChunkPosition, ContentKind, EdgeKind, EdgeOrigin, MetadataMap, NodeRef,
};

pub struct MarkdownAdapter;

impl MarkdownAdapter {
    pub const MAX_CHARS_PER_CHUNK: usize = 4000;
    pub const MIN_CHARS_PER_CHUNK: usize = 1;
}

impl Default for MarkdownAdapter {
    fn default() -> Self {
        Self
    }
}

impl ContentAdapter for MarkdownAdapter {
    fn kind(&self) -> ContentKind {
        ContentKind::Markdown
    }

    fn accepts(&self, hint: &MimeHint) -> bool {
        if let Some(mime) = &hint.mime {
            // Tolerate `text/markdown; charset=utf-8` and the legacy
            // `text/x-markdown` we see from some sources.
            if mime.starts_with("text/markdown") || mime.starts_with("text/x-markdown") {
                return true;
            }
        }
        if let Some(ext) = &hint.extension {
            if matches!(ext.as_str(), "md" | "markdown" | "mdown" | "mkd" | "mdx") {
                return true;
            }
        }
        false
    }

    fn ingest(&self, raw: RawDocument, _ctx: &IngestContext) -> IngestResult<IngestOutput> {
        let text = std::str::from_utf8(&raw.bytes)
            .map_err(|e| IngestError::Decode(format!("invalid utf-8: {e}")))?;
        let content_hash = *blake3::hash(text.as_bytes()).as_bytes();
        let mime = raw.mime_hint.clone().unwrap_or_else(|| "text/markdown".to_string());

        let mut metadata = raw.hint_metadata.clone();
        if metadata.size_bytes.is_none() {
            metadata.size_bytes = Some(raw.bytes.len() as u64);
        }
        if metadata.word_count.is_none() {
            metadata.word_count = Some(text.split_whitespace().count() as u32);
        }

        let parsed = parse_markdown(text);

        // Document title: prefer the first H1 if present.
        let title = parsed
            .sections
            .iter()
            .find(|s| s.heading_level == Some(HeadingLevel::H1))
            .map(|s| s.heading_text.clone())
            .filter(|t| !t.trim().is_empty())
            .or_else(|| {
                parsed
                    .sections
                    .iter()
                    .find_map(|s| s.heading_text.is_empty().then_some(()).map(|_| String::new()))
                    .map(|_| String::new())
                    .filter(|s| !s.is_empty())
            });

        let document = DocumentDraft {
            external_id: raw.external_id.clone(),
            kind: ContentKind::Markdown,
            mime,
            title,
            path_or_url: Some(raw.source_uri.clone()),
            content_hash,
            acl: Acl::default(),
            metadata,
            source_modified_at: raw.source_modified_at,
        };

        let mut chunks: Vec<ChunkDraft> = Vec::new();
        let mut embed_requests: Vec<EmbedRequest> = Vec::new();

        for section in &parsed.sections {
            for sub in subdivide_section(text, section, Self::MAX_CHARS_PER_CHUNK) {
                let trimmed = sub.text.trim();
                if trimmed.chars().count() < Self::MIN_CHARS_PER_CHUNK {
                    continue;
                }
                let idx = chunks.len();
                let mut tags: Vec<String> = Vec::new();
                if let Some(level) = section.heading_level {
                    tags.push(heading_tag(level).to_string());
                }
                let word_count = sub.text.split_whitespace().count() as u32;
                let kind = if section.heading_level.is_some() {
                    ChunkKind::Heading
                } else {
                    ChunkKind::Paragraph
                };
                chunks.push(ChunkDraft {
                    kind,
                    position: ChunkPosition::ByteRange { start: sub.start, end: sub.end },
                    text: sub.text.to_string(),
                    metadata: MetadataMap {
                        word_count: Some(word_count),
                        tags,
                        ..Default::default()
                    },
                });
                embed_requests.push(EmbedRequest {
                    target: EmbedTarget::Chunk(idx),
                    text: sub.text.to_string(),
                });
            }
        }

        // Inline links → `Cites` edges to externals.
        let mut edges: Vec<EdgeDraft> = Vec::new();
        for link in parsed.links {
            if link.url.is_empty() {
                continue;
            }
            let mut meta = MetadataMap::default();
            meta.extra = json!({
                "link_text": link.text,
                "title": link.title,
            });
            edges.push(EdgeDraft {
                from: EdgeEndpoint::Document,
                to: EdgeEndpoint::External(link.url),
                kind: EdgeKind::Cites,
                weight: 1.0,
                metadata: meta,
                created_by: EdgeOrigin::Adapter,
            });
        }

        // Suppress an unused warning on the convenience helper.
        let _ = NodeRef::External(String::new());

        Ok(IngestOutput {
            document,
            chunks,
            entities: Vec::new(),
            edges,
            embed_requests,
        })
    }

    fn ranking_signals(&self) -> &'static [SignalKind] {
        &[SignalKind::CosineThreshold(0.40), SignalKind::ZScoreNormalize]
    }

    fn relation_kinds(&self) -> &'static [EdgeKind] {
        &[EdgeKind::Cites]
    }
}

// ============================================================================
// Parsing
// ============================================================================

#[derive(Debug)]
struct ParsedDoc {
    sections: Vec<Section>,
    links: Vec<Link>,
}

#[derive(Debug)]
struct Section {
    /// Inclusive start byte in the source.
    start: usize,
    /// Exclusive end byte in the source.
    end: usize,
    /// `Some(level)` if the section begins with a heading; `None` for any
    /// preamble before the first heading.
    heading_level: Option<HeadingLevel>,
    /// The heading text (trimmed of formatting markers); empty for preamble.
    heading_text: String,
}

#[derive(Debug)]
struct Link {
    url: String,
    text: String,
    title: String,
}

/// Parse markdown into top-level sections (split at H1/H2) and collect all
/// inline link references.
fn parse_markdown(text: &str) -> ParsedDoc {
    let mut opts = Options::empty();
    opts.insert(Options::ENABLE_TABLES);
    opts.insert(Options::ENABLE_FOOTNOTES);
    opts.insert(Options::ENABLE_STRIKETHROUGH);
    opts.insert(Options::ENABLE_TASKLISTS);

    let parser = Parser::new_ext(text, opts).into_offset_iter();

    let mut section_starts: Vec<(usize, HeadingLevel)> = Vec::new();
    let mut heading_texts: Vec<(usize, String)> = Vec::new();
    let mut current_heading: Option<(usize, String)> = None; // (start, accumulated text)
    let mut links: Vec<Link> = Vec::new();
    let mut current_link: Option<(String, String, String)> = None; // (url, title, text)

    for (event, range) in parser {
        match event {
            Event::Start(Tag::Heading { level, .. }) => {
                if matches!(level, HeadingLevel::H1 | HeadingLevel::H2) {
                    section_starts.push((range.start, level));
                }
                current_heading = Some((range.start, String::new()));
            }
            Event::End(TagEnd::Heading(_)) => {
                if let Some((start, txt)) = current_heading.take() {
                    heading_texts.push((start, txt));
                }
            }
            Event::Start(Tag::Link { dest_url, title, .. }) => {
                current_link = Some((dest_url.to_string(), title.to_string(), String::new()));
            }
            Event::End(TagEnd::Link) => {
                if let Some((url, title, text)) = current_link.take() {
                    links.push(Link { url, text, title });
                }
            }
            Event::Text(t) => {
                if let Some((_, ref mut accum)) = current_heading {
                    accum.push_str(&t);
                }
                if let Some((_, _, ref mut accum)) = current_link {
                    accum.push_str(&t);
                }
            }
            Event::Code(t) => {
                if let Some((_, ref mut accum)) = current_heading {
                    accum.push_str(&t);
                }
                if let Some((_, _, ref mut accum)) = current_link {
                    accum.push_str(&t);
                }
            }
            _ => {}
        }
    }

    // Build section ranges by pairing consecutive starts.
    let mut sections: Vec<Section> = Vec::new();
    let preamble_end = section_starts.first().map(|(s, _)| *s).unwrap_or(text.len());
    if preamble_end > 0 {
        sections.push(Section {
            start: 0,
            end: preamble_end,
            heading_level: None,
            heading_text: String::new(),
        });
    }
    for (i, (start, level)) in section_starts.iter().enumerate() {
        let end = section_starts
            .get(i + 1)
            .map(|(s, _)| *s)
            .unwrap_or(text.len());
        let heading_text = heading_texts
            .iter()
            .find(|(s, _)| *s == *start)
            .map(|(_, t)| t.clone())
            .unwrap_or_default();
        sections.push(Section {
            start: *start,
            end,
            heading_level: Some(*level),
            heading_text,
        });
    }

    ParsedDoc { sections, links }
}

struct SubChunk<'a> {
    start: u64,
    end: u64,
    text: &'a str,
}

/// Sub-divide a section that exceeds `max_chars` into char-aligned pieces
/// with absolute byte offsets in the original source.
fn subdivide_section<'a>(
    full_text: &'a str,
    section: &Section,
    max_chars: usize,
) -> Vec<SubChunk<'a>> {
    if section.end <= section.start {
        return Vec::new();
    }
    let body = &full_text[section.start..section.end];
    if body.chars().count() <= max_chars {
        return vec![SubChunk {
            start: section.start as u64,
            end: section.end as u64,
            text: body,
        }];
    }
    let mut out = Vec::new();
    let mut char_count = 0usize;
    let mut window_start = 0usize;
    for (b, ch) in body.char_indices() {
        let byte_offset = b + ch.len_utf8();
        char_count += 1;
        if char_count >= max_chars {
            out.push(SubChunk {
                start: (section.start + window_start) as u64,
                end: (section.start + byte_offset) as u64,
                text: &body[window_start..byte_offset],
            });
            window_start = byte_offset;
            char_count = 0;
        }
    }
    if window_start < body.len() {
        out.push(SubChunk {
            start: (section.start + window_start) as u64,
            end: section.end as u64,
            text: &body[window_start..],
        });
    }
    out
}

fn heading_tag(level: HeadingLevel) -> &'static str {
    match level {
        HeadingLevel::H1 => "h1",
        HeadingLevel::H2 => "h2",
        HeadingLevel::H3 => "h3",
        HeadingLevel::H4 => "h4",
        HeadingLevel::H5 => "h5",
        HeadingLevel::H6 => "h6",
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    fn ctx() -> IngestContext {
        IngestContext {
            workspace_id: crate::types::WorkspaceId(1),
            source_id: crate::types::SourceId(1),
        }
    }

    fn raw(text: &str, uri: &str) -> RawDocument {
        RawDocument {
            bytes: text.as_bytes().to_vec(),
            source_uri: uri.to_string(),
            mime_hint: Some("text/markdown".to_string()),
            external_id: Some(uri.to_string()),
            hint_metadata: MetadataMap::default(),
            source_modified_at: None,
        }
    }

    #[test]
    fn accepts_md_mime_and_extensions() {
        let a = MarkdownAdapter;
        assert!(a.accepts(&MimeHint::from_mime("text/markdown; charset=utf-8")));
        assert!(a.accepts(&MimeHint::from_mime("text/x-markdown")));
        assert!(a.accepts(&MimeHint::from_uri("README.md")));
        assert!(a.accepts(&MimeHint::from_uri("notes.markdown")));
        assert!(a.accepts(&MimeHint::from_uri("page.mdx")));
        assert!(!a.accepts(&MimeHint::from_mime("text/plain")));
        assert!(!a.accepts(&MimeHint::from_uri("notes.txt")));
        assert!(!a.accepts(&MimeHint::default()));
    }

    #[test]
    fn empty_input_no_chunks() {
        let a = MarkdownAdapter;
        let out = a.ingest(raw("", "empty.md"), &ctx()).unwrap();
        assert!(out.chunks.is_empty());
        assert!(out.embed_requests.is_empty());
        assert_eq!(out.document.kind, ContentKind::Markdown);
    }

    #[test]
    fn h1_h2_split_into_separate_sections() {
        let a = MarkdownAdapter;
        let md = "# Title\n\nIntro text.\n\n## Auth\n\nJWT details.\n\n## Rate limiting\n\nSliding window.";
        let out = a.ingest(raw(md, "doc.md"), &ctx()).unwrap();
        assert_eq!(out.chunks.len(), 3, "expected 3 sections, got {:?}",
            out.chunks.iter().map(|c| &c.text).collect::<Vec<_>>());
        assert!(out.chunks[0].text.starts_with("# Title"));
        assert!(out.chunks[1].text.starts_with("## Auth"));
        assert!(out.chunks[2].text.starts_with("## Rate limiting"));
        assert_eq!(out.chunks[0].kind, ChunkKind::Heading);
        assert_eq!(out.document.title.as_deref(), Some("Title"));
    }

    #[test]
    fn preamble_before_first_heading_becomes_paragraph_chunk() {
        let a = MarkdownAdapter;
        let md = "Just some text.\n\n# Heading\n\nMore text.";
        let out = a.ingest(raw(md, "doc.md"), &ctx()).unwrap();
        assert_eq!(out.chunks.len(), 2);
        assert_eq!(out.chunks[0].kind, ChunkKind::Paragraph);
        assert!(out.chunks[0].text.starts_with("Just some text"));
        assert_eq!(out.chunks[1].kind, ChunkKind::Heading);
    }

    #[test]
    fn h3_does_not_split_section() {
        let a = MarkdownAdapter;
        let md = "## Section\n\n### Sub one\n\ntext\n\n### Sub two\n\ntext";
        let out = a.ingest(raw(md, "doc.md"), &ctx()).unwrap();
        // H3s stay inside the H2 section.
        assert_eq!(out.chunks.len(), 1);
        assert!(out.chunks[0].text.contains("Sub one"));
        assert!(out.chunks[0].text.contains("Sub two"));
    }

    #[test]
    fn links_emit_cites_edges() {
        let a = MarkdownAdapter;
        let md = "# Doc\n\nSee [Anthropic](https://anthropic.com) and [Postgres docs](https://postgresql.org/docs).";
        let out = a.ingest(raw(md, "doc.md"), &ctx()).unwrap();
        assert_eq!(out.edges.len(), 2);
        for edge in &out.edges {
            assert_eq!(edge.kind, EdgeKind::Cites);
            assert_eq!(edge.created_by, EdgeOrigin::Adapter);
            assert_eq!(edge.from, EdgeEndpoint::Document);
            match &edge.to {
                EdgeEndpoint::External(url) => {
                    assert!(url.starts_with("https://"), "got url={url}");
                }
                _ => panic!("expected external edge target"),
            }
        }
    }

    #[test]
    fn link_metadata_preserves_text() {
        let a = MarkdownAdapter;
        let md = "[click here](https://example.com \"the title\")";
        let out = a.ingest(raw(md, "doc.md"), &ctx()).unwrap();
        assert_eq!(out.edges.len(), 1);
        let extra = &out.edges[0].metadata.extra;
        assert_eq!(extra["link_text"].as_str(), Some("click here"));
        assert_eq!(extra["title"].as_str(), Some("the title"));
    }

    #[test]
    fn heading_chunks_carry_h1_h2_tags() {
        let a = MarkdownAdapter;
        let md = "# Top\n\n## Sub\n\nbody.";
        let out = a.ingest(raw(md, "doc.md"), &ctx()).unwrap();
        let h1 = out.chunks.iter().find(|c| c.text.starts_with("# Top")).unwrap();
        let h2 = out.chunks.iter().find(|c| c.text.starts_with("## Sub")).unwrap();
        assert_eq!(h1.metadata.tags, vec!["h1"]);
        assert_eq!(h2.metadata.tags, vec!["h2"]);
    }

    #[test]
    fn byte_positions_round_trip() {
        let a = MarkdownAdapter;
        let md = "# A\n\nfoo\n\n## B\n\nbar";
        let out = a.ingest(raw(md, "doc.md"), &ctx()).unwrap();
        for c in &out.chunks {
            match c.position {
                ChunkPosition::ByteRange { start, end } => {
                    let slice = &md[start as usize..end as usize];
                    assert_eq!(slice, c.text, "byte range did not slice back to text");
                }
                _ => panic!("expected byte range"),
            }
        }
    }

    #[test]
    fn oversize_section_is_subdivided() {
        let a = MarkdownAdapter;
        let mut md = String::from("# Big\n\n");
        md.push_str(&"x".repeat(MarkdownAdapter::MAX_CHARS_PER_CHUNK + 500));
        let out = a.ingest(raw(&md, "big.md"), &ctx()).unwrap();
        assert!(out.chunks.len() >= 2);
    }

    #[test]
    fn embed_requests_align_with_chunks() {
        let a = MarkdownAdapter;
        let md = "# A\n\nfoo\n\n# B\n\nbar";
        let out = a.ingest(raw(md, "doc.md"), &ctx()).unwrap();
        assert_eq!(out.embed_requests.len(), out.chunks.len());
        for (i, req) in out.embed_requests.iter().enumerate() {
            assert_eq!(req.target, EmbedTarget::Chunk(i));
            assert_eq!(req.text, out.chunks[i].text);
        }
    }

    #[test]
    fn content_hash_stable_for_same_input() {
        let a = MarkdownAdapter;
        let md = "# A\n\nbody";
        let out1 = a.ingest(raw(md, "doc.md"), &ctx()).unwrap();
        let out2 = a.ingest(raw(md, "doc.md"), &ctx()).unwrap();
        assert_eq!(out1.document.content_hash, out2.document.content_hash);
    }

    #[test]
    fn invalid_utf8_returns_decode_error() {
        let a = MarkdownAdapter;
        let bad = vec![0xFF, 0xFE];
        let r = RawDocument {
            bytes: bad,
            source_uri: "bad.md".into(),
            mime_hint: None,
            external_id: None,
            hint_metadata: MetadataMap::default(),
            source_modified_at: None,
        };
        let res = a.ingest(r, &ctx());
        assert!(matches!(res, Err(IngestError::Decode(_))));
    }

    #[test]
    fn relation_kinds_advertise_cites() {
        let a = MarkdownAdapter;
        assert_eq!(a.relation_kinds(), &[EdgeKind::Cites]);
    }
}
