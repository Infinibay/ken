//! `CodeAdapter` — multi-language source code via tree-sitter.
//!
//! Per-language walkers live in `rust.rs` and `python.rs`. This module
//! handles language detection (mime + extension), dispatch, and
//! IngestOutput assembly. Adding a new language is a 3-step add:
//!
//! 1. New `tree-sitter-<lang>` dep + `CodeLanguage` variant.
//! 2. New `<lang>.rs` walker that returns `Extracted { symbols, imports }`.
//! 3. Add the dispatch arm in `ingest`.
//!
//! All walkers return `Symbol`s with a *language-natural* qualified name
//! (`User::validate` for Rust, `User.validate` for Python) — preserving
//! the calling convention helps later tooling (jump-to-definition, etc.).

mod c_cpp;
mod go;
mod java;
mod js;
mod python;
mod ruby;
mod rust;
mod ts;

#[cfg(test)]
mod tests;

use tree_sitter::Node;

use crate::ingest::{
    ChunkDraft, ContentAdapter, DocumentDraft, EdgeDraft, EdgeEndpoint, EmbedRequest, EmbedTarget,
    IngestContext, IngestError, IngestOutput, IngestResult, MimeHint, RawDocument, SignalKind,
};
use crate::types::{
    Acl, ChunkKind, ChunkPosition, ContentKind, EdgeKind, EdgeOrigin, Language as LangEnum,
    MetadataMap,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CodeLanguage {
    Rust,
    Python,
    /// Plain TypeScript — uses `LANGUAGE_TYPESCRIPT` grammar (no JSX).
    Typescript,
    /// TypeScript-with-JSX — uses `LANGUAGE_TSX` grammar.
    Tsx,
    Go,
    JavaScript,
    Java,
    C,
    Cpp,
    Ruby,
}

impl CodeLanguage {
    fn to_language_enum(self) -> LangEnum {
        match self {
            CodeLanguage::Rust => LangEnum::Rust,
            CodeLanguage::Python => LangEnum::Python,
            CodeLanguage::Typescript | CodeLanguage::Tsx => LangEnum::TypeScript,
            CodeLanguage::Go => LangEnum::Go,
            CodeLanguage::JavaScript => LangEnum::JavaScript,
            CodeLanguage::Java => LangEnum::Java,
            CodeLanguage::C => LangEnum::C,
            CodeLanguage::Cpp => LangEnum::Cpp,
            CodeLanguage::Ruby => LangEnum::Ruby,
        }
    }

    pub(crate) fn detect_for_path(uri: &str) -> Option<Self> {
        Self::detect(&MimeHint { mime: None, extension: extension_from_uri(uri) })
    }

    pub(crate) fn detect(hint: &MimeHint) -> Option<Self> {
        if let Some(mime) = &hint.mime {
            if mime.starts_with("text/x-rust") || mime.starts_with("text/rust") {
                return Some(CodeLanguage::Rust);
            }
            if mime.starts_with("text/x-python") || mime.starts_with("text/python") {
                return Some(CodeLanguage::Python);
            }
            if mime.starts_with("text/x-typescript") || mime.starts_with("text/typescript") {
                return Some(CodeLanguage::Typescript);
            }
            if mime.starts_with("text/tsx") || mime.starts_with("text/x-tsx") {
                return Some(CodeLanguage::Tsx);
            }
            if mime.starts_with("text/x-go") || mime.starts_with("text/go") {
                return Some(CodeLanguage::Go);
            }
            if mime.starts_with("text/javascript")
                || mime.starts_with("application/javascript")
                || mime.starts_with("text/x-javascript")
            {
                return Some(CodeLanguage::JavaScript);
            }
            if mime.starts_with("text/x-java") || mime.starts_with("text/java") {
                return Some(CodeLanguage::Java);
            }
            if mime.starts_with("text/x-c++") || mime.starts_with("text/x-cpp") {
                return Some(CodeLanguage::Cpp);
            }
            if mime.starts_with("text/x-c") {
                return Some(CodeLanguage::C);
            }
            if mime.starts_with("text/x-ruby") || mime.starts_with("application/x-ruby") {
                return Some(CodeLanguage::Ruby);
            }
        }
        if let Some(ext) = &hint.extension {
            return match ext.as_str() {
                "rs" => Some(CodeLanguage::Rust),
                "py" | "pyi" => Some(CodeLanguage::Python),
                "ts" | "mts" | "cts" => Some(CodeLanguage::Typescript),
                "tsx" => Some(CodeLanguage::Tsx),
                "go" => Some(CodeLanguage::Go),
                "js" | "mjs" | "cjs" | "jsx" => Some(CodeLanguage::JavaScript),
                "java" => Some(CodeLanguage::Java),
                "c" | "h" => Some(CodeLanguage::C),
                "cpp" | "cc" | "cxx" | "hpp" | "hh" | "hxx" => Some(CodeLanguage::Cpp),
                "rb" | "rake" | "gemspec" => Some(CodeLanguage::Ruby),
                _ => None,
            };
        }
        None
    }

    fn default_mime(self) -> &'static str {
        match self {
            CodeLanguage::Rust => "text/x-rust",
            CodeLanguage::Python => "text/x-python",
            CodeLanguage::Typescript => "text/typescript",
            CodeLanguage::Tsx => "text/tsx",
            CodeLanguage::Go => "text/x-go",
            CodeLanguage::JavaScript => "text/javascript",
            CodeLanguage::Java => "text/x-java",
            CodeLanguage::C => "text/x-c",
            CodeLanguage::Cpp => "text/x-c++",
            CodeLanguage::Ruby => "text/x-ruby",
        }
    }

}

pub struct CodeAdapter;

impl CodeAdapter {
    /// Cap on individual symbol chunk size. Symbols larger than this are
    /// split char-aligned (long auto-generated impls, big classes).
    pub const MAX_CHARS_PER_CHUNK: usize = 6000;
}

impl Default for CodeAdapter {
    fn default() -> Self {
        Self
    }
}

impl ContentAdapter for CodeAdapter {
    fn kind(&self) -> ContentKind {
        ContentKind::CodeFile
    }

    fn accepts(&self, hint: &MimeHint) -> bool {
        CodeLanguage::detect(hint).is_some()
    }

    fn ingest(&self, raw: RawDocument, _ctx: &IngestContext) -> IngestResult<IngestOutput> {
        let detect_hint = MimeHint {
            mime: raw.mime_hint.clone(),
            extension: extension_from_uri(&raw.source_uri),
        };
        let lang = CodeLanguage::detect(&detect_hint).ok_or_else(|| {
            IngestError::Unsupported("could not detect code language".into())
        })?;

        let text = std::str::from_utf8(&raw.bytes)
            .map_err(|e| IngestError::Decode(format!("invalid utf-8: {e}")))?
            .to_string();
        let content_hash = *blake3::hash(text.as_bytes()).as_bytes();
        let mime = raw
            .mime_hint
            .clone()
            .unwrap_or_else(|| lang.default_mime().to_string());

        let mut metadata = raw.hint_metadata.clone();
        if metadata.size_bytes.is_none() {
            metadata.size_bytes = Some(raw.bytes.len() as u64);
        }
        if metadata.word_count.is_none() {
            metadata.word_count = Some(text.split_whitespace().count() as u32);
        }
        if metadata.language.is_none() {
            metadata.language = Some(lang.to_language_enum());
        }

        let extracted = match lang {
            CodeLanguage::Rust => rust::extract(&text)?,
            CodeLanguage::Python => python::extract(&text)?,
            CodeLanguage::Typescript => ts::extract(&text, false)?,
            CodeLanguage::Tsx => ts::extract(&text, true)?,
            CodeLanguage::Go => go::extract(&text)?,
            CodeLanguage::JavaScript => js::extract(&text)?,
            CodeLanguage::Java => java::extract(&text)?,
            CodeLanguage::C => c_cpp::extract(&text, false)?,
            CodeLanguage::Cpp => c_cpp::extract(&text, true)?,
            CodeLanguage::Ruby => ruby::extract(&text)?,
        };

        let document = DocumentDraft {
            external_id: raw.external_id.clone(),
            kind: ContentKind::CodeFile,
            mime,
            title: extracted
                .symbols
                .first()
                .map(|s| s.qualified_name.clone())
                .filter(|t| !t.is_empty()),
            path_or_url: Some(raw.source_uri.clone()),
            content_hash,
            acl: Acl::default(),
            metadata,
            source_modified_at: raw.source_modified_at,
        };

        let mut chunks: Vec<ChunkDraft> = Vec::new();
        let mut embed_requests: Vec<EmbedRequest> = Vec::new();
        for symbol in extracted.symbols {
            for piece in symbol.split(Self::MAX_CHARS_PER_CHUNK) {
                let idx = chunks.len();
                let mut tags = vec![piece.kind_tag.to_string()];
                if piece.is_method {
                    tags.push("method".into());
                }
                chunks.push(ChunkDraft {
                    kind: ChunkKind::CodeSymbol,
                    position: ChunkPosition::SymbolRange {
                        qualified_name: piece.qualified_name.clone(),
                        line_start: piece.line_start,
                        line_end: piece.line_end,
                    },
                    text: piece.text.clone(),
                    metadata: MetadataMap {
                        language: Some(lang.to_language_enum()),
                        tags,
                        word_count: Some(piece.text.split_whitespace().count() as u32),
                        ..Default::default()
                    },
                });
                embed_requests.push(EmbedRequest {
                    target: EmbedTarget::Chunk(idx),
                    text: piece.text,
                });
            }
        }

        // Walkers return import strings already namespaced
        // (`rust:foo::Bar`, `python:foo.bar`, `ts:./mod`, `npm:react`) so
        // mixed prefixes (TS relative vs npm) don't need special handling
        // in the orchestrator.
        let edges: Vec<EdgeDraft> = extracted
            .imports
            .into_iter()
            .map(|path| EdgeDraft {
                from: EdgeEndpoint::Document,
                to: EdgeEndpoint::External(path),
                kind: EdgeKind::Imports,
                weight: 1.0,
                metadata: MetadataMap::default(),
                created_by: EdgeOrigin::Adapter,
            })
            .collect();

        Ok(IngestOutput {
            document,
            chunks,
            entities: Vec::new(),
            edges,
            embed_requests,
        })
    }

    fn ranking_signals(&self) -> &'static [SignalKind] {
        // Code embeddings are noisier than prose under prose-trained models;
        // a slightly stricter cosine floor reduces false positives.
        &[SignalKind::CosineThreshold(0.45), SignalKind::ZScoreNormalize]
    }

    fn relation_kinds(&self) -> &'static [EdgeKind] {
        &[EdgeKind::Imports, EdgeKind::Defines]
    }
}

// ============================================================================
// Shared types used by per-language walkers
// ============================================================================

#[derive(Debug, Clone)]
pub(crate) struct Symbol {
    pub qualified_name: String,
    /// 1-indexed line numbers, inclusive.
    pub line_start: u32,
    pub line_end: u32,
    pub text: String,
    pub kind_tag: &'static str,
    pub is_method: bool,
}

impl Symbol {
    pub fn split(&self, max_chars: usize) -> Vec<Symbol> {
        if self.text.chars().count() <= max_chars {
            return vec![self.clone()];
        }
        let mut out = Vec::new();
        let mut buf = String::new();
        let mut count = 0usize;
        let mut piece_idx = 0usize;
        for ch in self.text.chars() {
            buf.push(ch);
            count += 1;
            if count >= max_chars {
                out.push(Symbol {
                    qualified_name: format!("{}#{}", self.qualified_name, piece_idx),
                    line_start: self.line_start,
                    line_end: self.line_end,
                    text: std::mem::take(&mut buf),
                    kind_tag: self.kind_tag,
                    is_method: self.is_method,
                });
                count = 0;
                piece_idx += 1;
            }
        }
        if !buf.is_empty() {
            out.push(Symbol {
                qualified_name: format!("{}#{}", self.qualified_name, piece_idx),
                line_start: self.line_start,
                line_end: self.line_end,
                text: buf,
                kind_tag: self.kind_tag,
                is_method: self.is_method,
            });
        }
        out
    }
}

pub(crate) struct Extracted {
    pub symbols: Vec<Symbol>,
    pub imports: Vec<String>,
}

pub(crate) fn node_text<'a>(node: Node, source: &'a str) -> &'a str {
    &source[node.start_byte()..node.end_byte()]
}

pub(crate) fn recompute_line_start(source: &str, byte_pos: usize) -> u32 {
    let mut line = 1u32;
    for &b in &source.as_bytes()[..byte_pos] {
        if b == b'\n' {
            line += 1;
        }
    }
    line
}

pub(crate) fn field_text(node: Node, field: &str, source: &str) -> Option<String> {
    node.child_by_field_name(field).map(|n| node_text(n, source).to_string())
}

/// Crate-visible dispatcher used by `ingest_git::symbols` (Phase 1.5) to
/// extract symbols from arbitrary file content without going through the
/// full `ContentAdapter::ingest` path. Mirrors the language switch in
/// `CodeAdapter::ingest`.
pub(crate) fn extract_symbols(
    language: CodeLanguage,
    text: &str,
) -> IngestResult<Extracted> {
    match language {
        CodeLanguage::Rust => rust::extract(text),
        CodeLanguage::Python => python::extract(text),
        CodeLanguage::Typescript => ts::extract(text, false),
        CodeLanguage::Tsx => ts::extract(text, true),
        CodeLanguage::Go => go::extract(text),
        CodeLanguage::JavaScript => js::extract(text),
        CodeLanguage::Java => java::extract(text),
        CodeLanguage::C => c_cpp::extract(text, false),
        CodeLanguage::Cpp => c_cpp::extract(text, true),
        CodeLanguage::Ruby => ruby::extract(text),
    }
}

fn extension_from_uri(uri: &str) -> Option<String> {
    uri.rsplit('/')
        .next()
        .and_then(|name| name.rsplit_once('.'))
        .map(|(_, ext)| ext.to_ascii_lowercase())
}
