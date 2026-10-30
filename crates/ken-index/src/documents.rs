use crate::{
    DocumentEncoder, IndexError, PreparedFile, Result,
    intents::{collapse, stem},
};
use ken_text::unicode::whitespace;
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum DocumentTarget {
    File,
    Symbol(usize),
    SymbolDoc(usize),
    ModuleDoc,
    PlainIntent(usize),
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Document {
    pub target: DocumentTarget,
    pub text: String,
}
pub fn symbol_text(kind: &str, name: &str, doc: Option<&str>) -> String {
    let tail = doc.unwrap_or("").trim_matches(whitespace);
    if tail.is_empty() {
        format!("{kind} {name}")
    } else {
        format!("{kind} {name} — {tail}")
    }
}
pub fn intent_text(kind: &str, text: &str) -> String {
    format!("{kind} — {}", collapse(text))
}
pub fn file_text(language: Option<&str>, path: &str, top: &[&str]) -> String {
    let head = format!(
        "{} {}",
        language.filter(|s| !s.is_empty()).unwrap_or("text"),
        stem(path)
    );
    if top.is_empty() {
        head
    } else {
        format!("{head} — {}", top.join(" "))
    }
}
pub(crate) fn for_file(file: &PreparedFile) -> Vec<Document> {
    let mut out = Vec::new();
    let mut add = |target, text| out.push(Document { target, text });
    if let Some(parsed) = &file.parsed {
        for (i, s) in parsed.symbols.iter().enumerate() {
            add(
                DocumentTarget::Symbol(i),
                symbol_text(&s.kind, &s.name, s.docstring.as_deref()),
            );
            if let Some(doc) = s.docstring.as_deref().filter(|s| !s.is_empty()) {
                add(
                    DocumentTarget::SymbolDoc(i),
                    intent_text("symbol_docstring", doc),
                );
            }
        }
        let top: Vec<_> = parsed
            .symbols
            .iter()
            .take(8)
            .map(|s| s.name.as_str())
            .collect();
        add(
            DocumentTarget::File,
            file_text(file.source.language.as_deref(), &file.source.path, &top),
        );
        if let Some(doc) = parsed.docstring.as_deref().filter(|s| !s.is_empty()) {
            add(
                DocumentTarget::ModuleDoc,
                intent_text("module_docstring", doc),
            );
        }
    } else {
        let top: Vec<_> = file
            .intent_texts
            .iter()
            .take(1)
            .map(String::as_str)
            .collect();
        add(
            DocumentTarget::File,
            file_text(None, &file.source.path, &top),
        );
        for (i, text) in file.intent_texts.iter().enumerate() {
            add(
                DocumentTarget::PlainIntent(i),
                intent_text("plain_text", text),
            );
        }
    }
    out
}
pub fn encode_pending(files: &mut [PreparedFile], encoder: &dyn DocumentEncoder) -> Result<()> {
    let texts: Vec<_> = files
        .iter()
        .flat_map(|f| f.documents.iter().map(|d| d.text.as_str()))
        .collect();
    if texts.is_empty() {
        return Ok(());
    }
    let vectors = encoder.embed_passages(&texts)?;
    if vectors.len() != texts.len() {
        return Err(IndexError::Invalid(
            "encoder document/vector counts differ".into(),
        ));
    }
    let dim = encoder.dim()?;
    if dim == 0
        || vectors
            .iter()
            .any(|v| v.len() != dim || v.iter().any(|n| !n.is_finite()))
    {
        return Err(IndexError::Invalid(
            "document vectors must be finite and match encoder dimension".into(),
        ));
    }
    let mut vectors = vectors.into_iter();
    for file in files {
        for d in &file.documents {
            file.vectors
                .insert(d.target.clone(), vectors.next().expect("validated lengths"));
        }
    }
    Ok(())
}
