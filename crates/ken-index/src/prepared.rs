use crate::{Document, DocumentTarget, Result, documents, intents};
use ken_retrieval::{Passage, PassagePolicy, TokenCounter, extract_passages};
use ken_syntax::ParsedFile;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashSet};
#[derive(Clone, Debug)]
pub struct SourceMetadata {
    pub path: String,
    pub language: Option<String>,
    pub content_hash: [u8; 32],
    pub mtime_ns: i64,
    pub order: usize,
}
#[derive(Clone, Debug)]
pub struct PreparedFile {
    pub source: SourceMetadata,
    pub parsed: Option<ParsedFile>,
    pub source_sha256: String,
    pub passages: Vec<Passage>,
    pub intent_texts: Vec<String>,
    pub documents: Vec<Document>,
    pub vectors: BTreeMap<DocumentTarget, Vec<f32>>,
}
impl PreparedFile {
    pub fn new(
        source: SourceMetadata,
        bytes: &[u8],
        mut parsed: Option<ParsedFile>,
        policy: &PassagePolicy,
        counter: &dyn TokenCounter,
    ) -> Result<Self> {
        if let Some(parsed) = &mut parsed {
            let mut known: HashSet<_> = parsed
                .symbols
                .iter()
                .map(|s| (s.kind.clone(), s.qualname.clone(), s.line_start))
                .collect();
            for scope in &parsed.scopes {
                let s = &scope.symbol;
                if known.insert((s.kind.clone(), s.qualname.clone(), s.line_start)) {
                    parsed.symbols.push(s.clone());
                }
            }
            parsed.symbols.sort_by(|a, b| {
                a.line_start
                    .cmp(&b.line_start)
                    .then_with(|| b.line_end.cmp(&a.line_end))
            });
        }
        let intent_texts = if source.language.is_none() {
            intents::plain_text_intents(&source.path, bytes)
        } else {
            vec![]
        };
        let passages = extract_passages(
            bytes,
            parsed.as_ref().unwrap_or(&ParsedFile::default()),
            &source.path,
            source.language.as_deref().unwrap_or("text"),
            policy,
            counter,
        )?;
        let mut file = Self {
            source,
            parsed,
            source_sha256: format!("{:x}", Sha256::digest(bytes)),
            passages,
            intent_texts,
            documents: vec![],
            vectors: BTreeMap::new(),
        };
        file.documents = documents::for_file(&file);
        Ok(file)
    }
}
