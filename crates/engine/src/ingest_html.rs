//! HTML → text adapter. Strips `<script>` / `<style>` blocks, removes the
//! remaining tags, decodes a small set of HTML entities, and chunks at
//! `<h1>`/`<h2>` boundaries (mirroring the Markdown adapter) so heading-
//! level structure is preserved as `["h1"]`/`["h2"]` chunk tags.
//!
//! Hand-rolled (no `scraper` / `html5ever` dep) because the upstream use
//! cases are documentation pages and blog posts where strict spec
//! conformance isn't required — the embeddings only care about the text.

use crate::ingest::{
    ChunkDraft, ContentAdapter, DocumentDraft, EmbedRequest, EmbedTarget, IngestContext,
    IngestError, IngestOutput, IngestResult, MimeHint, RawDocument, SignalKind,
};
use crate::types::{Acl, ChunkKind, ChunkPosition, ContentKind, EdgeKind, MetadataMap};

pub struct HtmlAdapter;

impl HtmlAdapter {
    pub const MAX_CHARS_PER_CHUNK: usize = 4000;
    pub const MIN_CHARS_PER_CHUNK: usize = 1;
}

impl Default for HtmlAdapter {
    fn default() -> Self {
        Self
    }
}

impl ContentAdapter for HtmlAdapter {
    fn kind(&self) -> ContentKind {
        ContentKind::Html
    }

    fn accepts(&self, hint: &MimeHint) -> bool {
        if let Some(mime) = &hint.mime
            && (mime.starts_with("text/html") || mime.starts_with("application/xhtml"))
        {
            return true;
        }
        if let Some(ext) = &hint.extension
            && matches!(ext.as_str(), "html" | "htm" | "xhtml")
        {
            return true;
        }
        false
    }

    fn ingest(&self, raw: RawDocument, _ctx: &IngestContext) -> IngestResult<IngestOutput> {
        let html = std::str::from_utf8(&raw.bytes)
            .map_err(|e| IngestError::Decode(format!("invalid utf-8: {e}")))?;
        let title = extract_title(html);
        let content_hash = *blake3::hash(html.as_bytes()).as_bytes();
        let mime = raw.mime_hint.clone().unwrap_or_else(|| "text/html".to_string());

        let sections = find_sections(html);

        let mut chunks: Vec<ChunkDraft> = Vec::new();
        let mut embed_requests: Vec<EmbedRequest> = Vec::new();
        let mut total_word_count: u32 = 0;
        for section in &sections {
            let stripped = strip_html_to_text(&html[section.start..section.end]);
            if stripped.trim().chars().count() < Self::MIN_CHARS_PER_CHUNK {
                continue;
            }
            let tag = section.heading_level.map(|lv| format!("h{lv}"));
            let pieces = split_section_chars(&stripped, Self::MAX_CHARS_PER_CHUNK);
            for (idx_in_section, piece) in pieces.iter().enumerate() {
                if piece.trim().chars().count() < Self::MIN_CHARS_PER_CHUNK {
                    continue;
                }
                let kind = if section.heading_level.is_some() && idx_in_section == 0 {
                    ChunkKind::Heading
                } else {
                    ChunkKind::Paragraph
                };
                let word_count = piece.split_whitespace().count() as u32;
                total_word_count = total_word_count.saturating_add(word_count);
                let mut tags: Vec<String> = Vec::new();
                if let Some(t) = &tag {
                    tags.push(t.clone());
                }
                let idx = chunks.len();
                chunks.push(ChunkDraft {
                    kind,
                    position: ChunkPosition::ByteRange {
                        start: section.start as u64,
                        end: section.end as u64,
                    },
                    text: piece.clone(),
                    metadata: MetadataMap {
                        word_count: Some(word_count),
                        tags,
                        ..Default::default()
                    },
                });
                embed_requests.push(EmbedRequest {
                    target: EmbedTarget::Chunk(idx),
                    text: piece.clone(),
                });
            }
        }

        let mut metadata = raw.hint_metadata.clone();
        if metadata.size_bytes.is_none() {
            metadata.size_bytes = Some(raw.bytes.len() as u64);
        }
        if metadata.word_count.is_none() {
            metadata.word_count = Some(total_word_count);
        }

        let document = DocumentDraft {
            external_id: raw.external_id.clone(),
            kind: ContentKind::Html,
            mime,
            title,
            path_or_url: Some(raw.source_uri.clone()),
            content_hash,
            acl: Acl::default(),
            metadata,
            source_modified_at: raw.source_modified_at,
        };

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

#[derive(Debug, Clone, Copy)]
struct HtmlSection {
    /// Inclusive byte offset into the original HTML where this section begins.
    start: usize,
    /// Exclusive byte offset into the original HTML where this section ends.
    end: usize,
    /// `Some(1)` for `<h1>`, `Some(2)` for `<h2>`; `None` for the preamble
    /// before the first heading.
    heading_level: Option<u8>,
}

/// Walk `html` once to locate `<h1>` / `<h2>` opening tags and partition
/// the document into sections. Skips matches inside `<script>` / `<style>`.
fn find_sections(html: &str) -> Vec<HtmlSection> {
    let bytes = html.as_bytes();
    let mut starts: Vec<(usize, u8)> = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if let Some(end) = skip_block(html, i, "script") {
            i = end;
            continue;
        }
        if let Some(end) = skip_block(html, i, "style") {
            i = end;
            continue;
        }
        if bytes[i] == b'<' && i + 3 < bytes.len() {
            let h = bytes[i + 1];
            let n = bytes[i + 2];
            let after = bytes[i + 3];
            let is_h = h == b'h' || h == b'H';
            let level = if n == b'1' { Some(1u8) } else if n == b'2' { Some(2u8) } else { None };
            let boundary = matches!(after, b'>' | b' ' | b'\t' | b'\n' | b'\r' | b'/');
            if is_h && level.is_some() && boundary {
                starts.push((i, level.unwrap()));
            }
        }
        i += 1;
    }

    let mut sections = Vec::new();
    let preamble_end = starts.first().map(|(s, _)| *s).unwrap_or(html.len());
    if preamble_end > 0 {
        sections.push(HtmlSection {
            start: 0,
            end: preamble_end,
            heading_level: None,
        });
    }
    for (i, (start, level)) in starts.iter().enumerate() {
        let end = starts.get(i + 1).map(|(s, _)| *s).unwrap_or(html.len());
        sections.push(HtmlSection {
            start: *start,
            end,
            heading_level: Some(*level),
        });
    }
    sections
}

/// Split a section's stripped plain text into char-aligned pieces. If the
/// whole section fits under `max_chars` returns it as a single piece;
/// otherwise emits sub-pieces of at most `max_chars` chars each (UTF-8 safe).
fn split_section_chars(text: &str, max_chars: usize) -> Vec<String> {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return Vec::new();
    }
    if trimmed.chars().count() <= max_chars {
        return vec![trimmed.to_string()];
    }
    let mut out = Vec::new();
    let mut window_start = 0usize;
    let mut count = 0usize;
    let bytes = trimmed.as_bytes();
    for (b, ch) in trimmed.char_indices() {
        count += 1;
        if count >= max_chars {
            let end = b + ch.len_utf8();
            out.push(trimmed[window_start..end].to_string());
            window_start = end;
            count = 0;
        }
    }
    if window_start < bytes.len() {
        out.push(trimmed[window_start..].to_string());
    }
    out
}

/// Extract the `<title>` tag's inner text. Returns `None` if absent or empty
/// after trimming. Cheap — single ASCII-case-insensitive scan.
fn extract_title(html: &str) -> Option<String> {
    let lower = html.to_ascii_lowercase();
    let open = lower.find("<title")?;
    let after_open = open + html[open..].find('>')? + 1;
    let close_rel = lower[after_open..].find("</title>")?;
    let raw = &html[after_open..after_open + close_rel];
    let decoded = decode_entities(raw);
    let trimmed = decoded.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

/// Strip HTML to plain text. Two passes:
///   1. Drop everything inside `<script>...</script>` and `<style>...</style>`
///      (case-insensitive). These contain JS / CSS that would pollute the
///      embeddings.
///   2. Walk the remaining bytes, copying non-tag characters and emitting a
///      single space whenever a tag closes (`>`) so adjacent words don't
///      collide. Decode entities, collapse runs of whitespace into one
///      space, and preserve paragraph breaks (`\n\n`) created by block-
///      level tags.
pub fn strip_html_to_text(html: &str) -> String {
    let mut buf = String::with_capacity(html.len() / 2);
    let bytes = html.as_bytes();
    let mut i = 0;
    let mut in_tag = false;
    let mut current_tag = String::new();
    while i < bytes.len() {
        // Skip script/style content wholesale — case-insensitive open/close.
        if !in_tag
            && let Some(end) = skip_block(html, i, "script")
        {
            i = end;
            buf.push(' ');
            continue;
        }
        if !in_tag
            && let Some(end) = skip_block(html, i, "style")
        {
            i = end;
            buf.push(' ');
            continue;
        }
        let c = bytes[i] as char;
        if c == '<' {
            in_tag = true;
            current_tag.clear();
            i += 1;
            continue;
        }
        if c == '>' {
            in_tag = false;
            // Block-level tags get a paragraph break so adjacent <p>foo</p>
            // <p>bar</p> doesn't collapse to "foo bar".
            if is_block_tag(&current_tag) {
                buf.push('\n');
                buf.push('\n');
            } else {
                buf.push(' ');
            }
            i += 1;
            continue;
        }
        if in_tag {
            current_tag.push(c.to_ascii_lowercase());
            i += 1;
            continue;
        }
        if c == '&' {
            // Try to decode an entity ending in `;` within the next 16 bytes.
            // Anything longer is almost certainly malformed — emit the `&`.
            if let Some(end) = bytes[i + 1..i + 17.min(bytes.len() - i)]
                .iter()
                .position(|&b| b == b';')
            {
                let raw = &html[i..i + 1 + end + 1];
                let decoded = decode_entities(raw);
                buf.push_str(&decoded);
                i += 1 + end + 1;
                continue;
            }
        }
        buf.push(c);
        i += html[i..].chars().next().map(|ch| ch.len_utf8()).unwrap_or(1);
    }
    collapse_whitespace(&buf)
}

/// If `html[start..]` opens a `<tag ...>` (case-insensitive), return the byte
/// offset just past the matching `</tag>`. Otherwise `None`. Lets us skip
/// `<script>` / `<style>` bodies in one shot.
fn skip_block(html: &str, start: usize, tag: &str) -> Option<usize> {
    let bytes = html.as_bytes();
    if bytes.get(start) != Some(&b'<') {
        return None;
    }
    let after_lt = start + 1;
    let rest = html.get(after_lt..)?;
    if rest.len() < tag.len() {
        return None;
    }
    if !rest[..tag.len()].eq_ignore_ascii_case(tag) {
        return None;
    }
    // Must be followed by `>` or whitespace (to rule out e.g. `<scripts>`).
    let after_tag = after_lt + tag.len();
    let next = bytes.get(after_tag)?;
    if !matches!(*next, b'>' | b' ' | b'\t' | b'\n' | b'\r') {
        return None;
    }
    let close_marker = format!("</{tag}>");
    let lower_rest = html[after_lt..].to_ascii_lowercase();
    let close_rel = lower_rest.find(&close_marker)?;
    Some(after_lt + close_rel + close_marker.len())
}

fn is_block_tag(tag_open: &str) -> bool {
    // Strip the leading `/` (closing tag) and any whitespace; take the bare
    // tag name. Match against a block-level allowlist — paragraph break only
    // when these close.
    let name = tag_open
        .trim_start_matches('/')
        .split(|c: char| c.is_whitespace() || c == '/')
        .next()
        .unwrap_or("");
    matches!(
        name,
        "p" | "br"
            | "div"
            | "h1"
            | "h2"
            | "h3"
            | "h4"
            | "h5"
            | "h6"
            | "li"
            | "tr"
            | "section"
            | "article"
            | "header"
            | "footer"
            | "main"
            | "blockquote"
            | "pre"
            | "hr"
    )
}

/// Decode the small set of entities that show up regularly in real HTML.
/// Falls through unknown entities verbatim — agents tolerate this better than
/// dropping content silently. Numeric entities (`&#39;`, `&#x27;`) are also
/// decoded.
pub fn decode_entities(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut i = 0;
    let bytes = s.as_bytes();
    while i < bytes.len() {
        if bytes[i] == b'&'
            && let Some(end_rel) = s[i..].find(';')
        {
            let entity = &s[i..i + end_rel + 1];
            let replacement = match entity {
                "&amp;" => Some("&"),
                "&lt;" => Some("<"),
                "&gt;" => Some(">"),
                "&quot;" => Some("\""),
                "&apos;" => Some("'"),
                "&nbsp;" => Some(" "),
                "&copy;" => Some("©"),
                "&reg;" => Some("®"),
                "&hellip;" => Some("…"),
                "&mdash;" => Some("—"),
                "&ndash;" => Some("–"),
                "&laquo;" => Some("«"),
                "&raquo;" => Some("»"),
                _ => None,
            };
            if let Some(r) = replacement {
                out.push_str(r);
                i += entity.len();
                continue;
            }
            // Numeric: &#NNN; or &#xHH;
            if let Some(num_str) = entity
                .strip_prefix("&#")
                .and_then(|t| t.strip_suffix(';'))
            {
                let parsed = if let Some(hex) = num_str.strip_prefix(['x', 'X']) {
                    u32::from_str_radix(hex, 16).ok()
                } else {
                    num_str.parse::<u32>().ok()
                };
                if let Some(cp) = parsed
                    && let Some(ch) = char::from_u32(cp)
                {
                    out.push(ch);
                    i += entity.len();
                    continue;
                }
            }
            // Unknown entity — keep the raw text.
            out.push_str(entity);
            i += entity.len();
            continue;
        }
        out.push(bytes[i] as char);
        i += 1;
    }
    out
}

/// Collapse runs of whitespace, but preserve paragraph breaks (`\n\n`) so
/// the paragraph splitter downstream still sees a chunk boundary. Also
/// suppresses a single space that would otherwise sit between a word and
/// trailing punctuation — `<b>bold</b>.` becomes `bold.`, not `bold .`,
/// which is what the inline-tag space-on-close behavior would produce.
fn collapse_whitespace(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut last_was_ws = false;
    let mut newline_run = 0usize;
    for ch in s.chars() {
        if ch == '\n' {
            newline_run += 1;
            last_was_ws = true;
            continue;
        }
        if ch.is_whitespace() {
            last_was_ws = true;
            continue;
        }
        if newline_run >= 2 {
            // Paragraph break — emit one to mark separator.
            if !out.is_empty() {
                out.push('\n');
                out.push('\n');
            }
        } else if last_was_ws && !out.is_empty() && !is_close_punct(ch) {
            out.push(' ');
        }
        newline_run = 0;
        last_was_ws = false;
        out.push(ch);
    }
    out
}

/// Closing punctuation that shouldn't be preceded by a space when we're
/// gluing back text that an inline tag's close-quote split. Conservative
/// list — covers ASCII sentence/clause delimiters and common closers.
fn is_close_punct(ch: char) -> bool {
    matches!(ch, '.' | ',' | ';' | ':' | '!' | '?' | ')' | ']' | '}' | '"' | '\'')
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ingest::IngestContext;
    use crate::types::{SourceId, WorkspaceId};

    fn ctx() -> IngestContext {
        IngestContext {
            workspace_id: WorkspaceId(1),
            source_id: SourceId(1),
        }
    }

    fn raw(html: &str, uri: &str) -> RawDocument {
        RawDocument {
            bytes: html.as_bytes().to_vec(),
            source_uri: uri.to_string(),
            mime_hint: Some("text/html".to_string()),
            external_id: Some(uri.to_string()),
            hint_metadata: MetadataMap::default(),
            source_modified_at: None,
        }
    }

    #[test]
    fn h1_h2_split_into_separate_sections() {
        let a = HtmlAdapter;
        let html = "<html><body><h1>A</h1><p>x</p><h2>B</h2><p>y</p></body></html>";
        let out = a.ingest(raw(html, "doc.html"), &ctx()).unwrap();
        // Preamble (`<html><body>`) strips to empty → skipped.
        assert_eq!(out.chunks.len(), 2, "got {:?}", out.chunks.iter().map(|c| &c.text).collect::<Vec<_>>());
        assert_eq!(out.chunks[0].kind, ChunkKind::Heading);
        assert_eq!(out.chunks[0].metadata.tags, vec!["h1"]);
        assert!(out.chunks[0].text.contains('A'));
        assert!(out.chunks[0].text.contains('x'));
        assert_eq!(out.chunks[1].kind, ChunkKind::Heading);
        assert_eq!(out.chunks[1].metadata.tags, vec!["h2"]);
        assert!(out.chunks[1].text.contains('B'));
        assert!(out.chunks[1].text.contains('y'));
    }

    #[test]
    fn preamble_before_first_heading_is_paragraph() {
        let a = HtmlAdapter;
        let html = "<p>intro text</p><h1>Heading</h1><p>body</p>";
        let out = a.ingest(raw(html, "doc.html"), &ctx()).unwrap();
        assert_eq!(out.chunks.len(), 2);
        assert_eq!(out.chunks[0].kind, ChunkKind::Paragraph);
        assert!(out.chunks[0].metadata.tags.is_empty());
        assert!(out.chunks[0].text.contains("intro text"));
        assert_eq!(out.chunks[1].kind, ChunkKind::Heading);
        assert_eq!(out.chunks[1].metadata.tags, vec!["h1"]);
    }

    #[test]
    fn h3_does_not_split_section() {
        let a = HtmlAdapter;
        let html = "<h2>Sec</h2><h3>Sub one</h3><p>x</p><h3>Sub two</h3><p>y</p>";
        let out = a.ingest(raw(html, "doc.html"), &ctx()).unwrap();
        assert_eq!(out.chunks.len(), 1, "expected single h2 section");
        assert!(out.chunks[0].text.contains("Sub one"));
        assert!(out.chunks[0].text.contains("Sub two"));
    }

    #[test]
    fn no_headings_collapses_to_one_section() {
        let a = HtmlAdapter;
        let html = "<p>just</p><p>paragraphs</p>";
        let out = a.ingest(raw(html, "doc.html"), &ctx()).unwrap();
        assert_eq!(out.chunks.len(), 1);
        assert!(out.chunks[0].metadata.tags.is_empty());
    }

    #[test]
    fn byte_positions_cover_section_in_original_html() {
        let a = HtmlAdapter;
        let html = "<h1>A</h1><p>x</p><h2>B</h2><p>y</p>";
        let out = a.ingest(raw(html, "doc.html"), &ctx()).unwrap();
        for c in &out.chunks {
            match c.position {
                ChunkPosition::ByteRange { start, end } => {
                    let slice = &html[start as usize..end as usize];
                    // The slice must contain the heading or paragraph text.
                    let chunk_first_word = c.text.split_whitespace().next().unwrap_or("");
                    assert!(slice.contains(chunk_first_word),
                        "slice {slice:?} should contain chunk first word {chunk_first_word:?}");
                }
                _ => panic!("expected byte range"),
            }
        }
    }

    #[test]
    fn embed_requests_align_with_chunks() {
        let a = HtmlAdapter;
        let html = "<h1>A</h1><p>x</p><h2>B</h2><p>y</p>";
        let out = a.ingest(raw(html, "doc.html"), &ctx()).unwrap();
        assert_eq!(out.embed_requests.len(), out.chunks.len());
        for (i, req) in out.embed_requests.iter().enumerate() {
            assert_eq!(req.target, EmbedTarget::Chunk(i));
            assert_eq!(req.text, out.chunks[i].text);
        }
    }

    #[test]
    fn header_inside_script_is_ignored() {
        let a = HtmlAdapter;
        let html = "<script>var a = '<h1>nope</h1>';</script><h1>real</h1><p>body</p>";
        let out = a.ingest(raw(html, "doc.html"), &ctx()).unwrap();
        // Only one h1 section — the one inside <script> is skipped.
        let h1_chunks: Vec<_> = out.chunks.iter().filter(|c| c.metadata.tags == vec!["h1"]).collect();
        assert_eq!(h1_chunks.len(), 1);
        assert!(h1_chunks[0].text.contains("real"));
        assert!(!h1_chunks[0].text.contains("nope"));
    }

    #[test]
    fn invalid_utf8_returns_decode_error() {
        let a = HtmlAdapter;
        let bad = vec![0xFFu8, 0xFE];
        let r = RawDocument {
            bytes: bad,
            source_uri: "bad.html".into(),
            mime_hint: None,
            external_id: None,
            hint_metadata: MetadataMap::default(),
            source_modified_at: None,
        };
        let res = a.ingest(r, &ctx());
        assert!(matches!(res, Err(IngestError::Decode(_))));
    }

    #[test]
    fn strips_tags_and_decodes_entities() {
        let html = "<html><body><h1>Hi &amp; Bye</h1><p>This is <b>bold</b>.</p></body></html>";
        let text = strip_html_to_text(html);
        assert!(text.contains("Hi & Bye"));
        assert!(text.contains("This is bold."));
    }

    #[test]
    fn drops_script_and_style() {
        let html = "<style>p{color:red}</style><p>visible</p><script>alert('x')</script>";
        let text = strip_html_to_text(html);
        assert!(text.contains("visible"));
        assert!(!text.contains("color:red"));
        assert!(!text.contains("alert"));
    }

    #[test]
    fn paragraph_breaks_between_block_tags() {
        let html = "<p>first</p><p>second</p>";
        let text = strip_html_to_text(html);
        assert!(text.contains("first\n\nsecond"));
    }

    #[test]
    fn extracts_title() {
        assert_eq!(
            extract_title("<html><head><title>Hello &amp; World</title></head></html>"),
            Some("Hello & World".into())
        );
        assert_eq!(extract_title("<html></html>"), None);
    }

    #[test]
    fn numeric_entities() {
        assert_eq!(decode_entities("&#65;&#x42;C"), "ABC");
    }

    #[test]
    fn adapter_accepts_html_mimes_and_extensions() {
        let a = HtmlAdapter;
        assert!(a.accepts(&MimeHint::from_mime("text/html")));
        assert!(a.accepts(&MimeHint::from_mime("text/html; charset=utf-8")));
        assert!(a.accepts(&MimeHint::from_mime("application/xhtml+xml")));
        assert!(a.accepts(&MimeHint::from_uri("docs/index.html")));
        assert!(a.accepts(&MimeHint::from_uri("page.htm")));
        assert!(!a.accepts(&MimeHint::from_mime("text/plain")));
        assert!(!a.accepts(&MimeHint::from_uri("file.txt")));
    }
}
