use std::hash::{Hash, Hasher};

use ahash::AHasher;

/// Embedding backend. The trait is **asymmetric** because production
/// models like `nomic-embed-text-v1.5` produce different vectors for
/// passages-being-indexed vs queries-being-issued; mixing them breaks
/// retrieval calibration. Symmetric implementations (e.g. `MockEmbedder`)
/// are free to delegate one to the other.
///
/// The `'static` bound keeps embedders movable into `tokio::task::spawn_blocking`
/// closures — a real ONNX/Candle backend will block long enough that the
/// HTTP layer must dispatch it off the executor thread.
pub trait Embedder: Send + Sync + 'static {
    fn dim(&self) -> usize;

    /// Embed text being **stored / indexed** (chunks, session contexts).
    fn embed_passages(&self, texts: &[&str]) -> Vec<Vec<f32>>;

    /// Embed a **query** for retrieval. Asymmetric models prepend a
    /// dedicated query prefix internally; symmetric ones (mock) ignore it.
    fn embed_query(&self, text: &str) -> Vec<f32>;

    /// Convenience for a single passage.
    fn embed_passage(&self, text: &str) -> Vec<f32> {
        self.embed_passages(&[text]).into_iter().next().unwrap_or_default()
    }
}

pub struct MockEmbedder {
    dim: usize,
}

impl MockEmbedder {
    pub fn new(dim: usize) -> Self {
        assert!(dim >= 8, "mock embedder needs at least 8 dims");
        Self { dim }
    }
}

impl Default for MockEmbedder {
    fn default() -> Self {
        Self::new(64)
    }
}

impl Embedder for MockEmbedder {
    fn dim(&self) -> usize {
        self.dim
    }

    fn embed_passages(&self, texts: &[&str]) -> Vec<Vec<f32>> {
        texts.iter().map(|t| mock_vector(t, self.dim)).collect()
    }

    fn embed_query(&self, text: &str) -> Vec<f32> {
        mock_vector(text, self.dim)
    }
}

fn mock_vector(text: &str, dim: usize) -> Vec<f32> {
    let mut v = vec![0.0f32; dim];
    for tok in tokenize(text) {
        let mut h = AHasher::default();
        tok.hash(&mut h);
        let bucket = (h.finish() as usize) % dim;
        let mut h2 = AHasher::default();
        ("sign", &tok).hash(&mut h2);
        let sign = if h2.finish() & 1 == 0 { 1.0 } else { -1.0 };
        v[bucket] += sign;
    }
    l2_normalize(&mut v);
    v
}

fn tokenize(text: &str) -> impl Iterator<Item = String> + '_ {
    text.split(|c: char| !c.is_alphanumeric() && c != '_')
        .filter(|s| !s.is_empty())
        .map(|s| s.to_lowercase())
}

pub fn l2_normalize(v: &mut [f32]) {
    let mut norm: f32 = v.iter().map(|x| x * x).sum::<f32>().sqrt();
    if norm < 1e-12 {
        norm = 1.0;
    }
    for x in v.iter_mut() {
        *x /= norm;
    }
}

pub fn cosine(a: &[f32], b: &[f32]) -> f32 {
    if a.len() != b.len() || a.is_empty() {
        return 0.0;
    }
    let mut dot = 0.0f32;
    let mut na = 0.0f32;
    let mut nb = 0.0f32;
    for i in 0..a.len() {
        dot += a[i] * b[i];
        na += a[i] * a[i];
        nb += b[i] * b[i];
    }
    let denom = na.sqrt() * nb.sqrt();
    if denom < 1e-12 { 0.0 } else { dot / denom }
}

const COMMON_STOPWORDS: &[&str] = &[
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "when", "while",
    "of", "to", "in", "on", "at", "by", "for", "with", "from", "as", "is", "are",
    "was", "were", "be", "been", "being", "this", "that", "these", "those", "it",
    "its", "i", "you", "we", "they", "he", "she", "them", "us", "our", "your",
    "my", "me", "do", "does", "did", "doing", "have", "has", "had", "having",
    "can", "could", "should", "would", "may", "might", "must", "shall", "will",
    "not", "no", "yes", "so", "than", "such", "very", "just", "only", "really",
    "please", "help", "want", "need", "like", "make", "show", "tell", "give",
    "use", "using", "used", "let", "lets", "ok", "okay", "thanks", "thank",
    "how", "what", "why", "where", "when", "who", "which", "find", "search",
    "looking", "trying", "able", "way", "best", "good", "bad", "right", "wrong",
    "thing", "things", "stuff", "something", "anything", "nothing",
    "es", "el", "la", "los", "las", "un", "una", "unos", "unas", "y", "o", "pero",
    "si", "no", "de", "del", "al", "a", "en", "por", "para", "con", "sin", "sobre",
    "que", "como", "cuando", "donde", "porque", "muy", "mas", "menos", "tan",
    "esto", "eso", "este", "esta", "estos", "estas", "ese", "esa", "esos", "esas",
    "yo", "tu", "vos", "el", "ella", "nosotros", "ustedes", "ellos", "ellas",
    "ser", "estar", "tener", "hacer", "ir", "venir", "decir", "ver", "saber",
    "poder", "querer", "gustar", "deber", "necesitar", "ayuda", "favor",
    "ayudame", "muestrame", "dime", "decime", "explicame", "explicar", "buscar",
    "encontrar", "encontrame", "mostrar", "ver", "viendo", "mirar", "mirame",
    "cosa", "cosas", "algo", "nada", "todo", "todos", "todas",
];

pub fn simplified_for_symbol_search(query: &str) -> String {
    let kept: Vec<String> = tokenize(query)
        .filter(|tok| {
            if tok.len() < 3 {
                return false;
            }
            !COMMON_STOPWORDS.iter().any(|sw| *sw == tok.as_str())
        })
        .collect();
    kept.join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mock_is_deterministic() {
        let e = MockEmbedder::new(32);
        let a = e.embed_query("hello world");
        let b = e.embed_query("hello world");
        assert_eq!(a, b);
    }

    #[test]
    fn mock_has_correct_dim_and_norm() {
        let e = MockEmbedder::new(32);
        let v = e.embed_passage("some text here");
        assert_eq!(v.len(), 32);
        let n: f32 = v.iter().map(|x| x * x).sum::<f32>().sqrt();
        assert!((n - 1.0).abs() < 1e-5 || n == 0.0);
    }

    #[test]
    fn mock_distinguishes_text() {
        let e = MockEmbedder::new(64);
        let a = e.embed_passage("validate jwt token");
        let b = e.embed_passage("compute fft buffer");
        assert!(cosine(&a, &b) < 0.9);
    }

    #[test]
    fn mock_query_and_passage_match_for_same_text() {
        // MockEmbedder is symmetric — query and passage encodings agree.
        // Asymmetric models (FastEmbedder) intentionally disagree.
        let e = MockEmbedder::new(32);
        assert_eq!(e.embed_query("foo bar"), e.embed_passage("foo bar"));
    }

    #[test]
    fn cosine_basic() {
        let a = vec![1.0, 0.0, 0.0];
        let b = vec![1.0, 0.0, 0.0];
        let c = vec![0.0, 1.0, 0.0];
        assert!((cosine(&a, &b) - 1.0).abs() < 1e-6);
        assert!(cosine(&a, &c).abs() < 1e-6);
    }

    #[test]
    fn simplified_keeps_distinctive_tokens() {
        let s = simplified_for_symbol_search(
            "Could you please help me find the function that validates JWT tokens?",
        );
        assert!(s.contains("function"));
        assert!(s.contains("validates"));
        assert!(s.contains("jwt"));
        assert!(s.contains("tokens"));
        assert!(!s.contains("could"));
        assert!(!s.contains("please"));
        assert!(!s.contains("help"));
        assert!(!s.contains("find"));
    }

    #[test]
    fn simplified_handles_spanish() {
        let s = simplified_for_symbol_search(
            "por favor ayudame a encontrar la funcion que valida tokens JWT",
        );
        assert!(s.contains("funcion"));
        assert!(s.contains("valida"));
        assert!(s.contains("tokens"));
        assert!(s.contains("jwt"));
        assert!(!s.contains("favor"));
        assert!(!s.contains("ayudame"));
    }
}
