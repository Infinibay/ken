//! English stemming with provider-owned bounded reuse and independent word state.
use crate::{Result, RetrievalError, snowball};
use ken_text::PythonText;
use std::{
    collections::{BTreeSet, HashMap},
    sync::{Arc, Mutex, OnceLock},
};
const CAPACITY: usize = 32768;
const MAX_CACHED_POINTS: usize = 128;
pub trait WordStemmer: Send + Sync {
    fn stem(&self, word: &PythonText) -> Result<PythonText>;
}
struct EnglishAlgorithm;
impl WordStemmer for EnglishAlgorithm {
    fn stem(&self, word: &PythonText) -> Result<PythonText> {
        // The frozen grammar writes only ASCII and never deletes a non-ASCII
        // character. One non-vowel scalar therefore carries each lone surrogate.
        // Record real marker occurrences too, preserving collisions in order.
        const MARKER: char = '\u{e000}';
        let mut markers = Vec::new();
        let mut native = String::new();
        for &point in word.codepoints() {
            if (0xd800..=0xdfff).contains(&point) || point == u32::from(MARKER) {
                markers.push(point);
                native.push(MARKER);
            } else {
                native.push(char::from_u32(point).expect("Python scalar"));
            }
        }
        if native.len() > i32::MAX as usize - 8 {
            return Err(RetrievalError::Invalid(
                "English word exceeds native Snowball address space".into(),
            ));
        }
        let output = snowball::stem(&native);
        let mut markers = markers.into_iter();
        let mut result = Vec::new();
        for c in output.chars() {
            result.push(if c == MARKER {
                markers.next().ok_or_else(|| {
                    RetrievalError::Invalid("English stem marker invariant changed".into())
                })?
            } else {
                u32::from(c)
            });
        }
        if markers.next().is_some() {
            return Err(RetrievalError::Invalid(
                "English stem marker invariant changed".into(),
            ));
        }
        Ok(PythonText::from_codepoints(result).expect("preserved Python points"))
    }
}
struct Entry {
    value: PythonText,
    tick: u128,
}
#[derive(Default)]
struct Cache {
    clock: u128,
    entries: HashMap<Vec<u32>, Entry>,
    order: BTreeSet<(u128, Vec<u32>)>,
}
impl Cache {
    fn get(&mut self, key: &[u32]) -> Option<PythonText> {
        let entry = self.entries.get_mut(key)?;
        self.order.remove(&(entry.tick, key.to_vec()));
        self.clock += 1;
        entry.tick = self.clock;
        self.order.insert((entry.tick, key.to_vec()));
        Some(entry.value.clone())
    }
    fn insert(&mut self, key: Vec<u32>, value: PythonText) {
        // Another concurrent miss may have completed while this provider ran.
        if self.entries.contains_key(&key) {
            return;
        }
        if self.entries.len() == CAPACITY {
            let (_, old) = self.order.pop_first().expect("nonempty bounded cache");
            self.entries.remove(&old);
        }
        self.clock += 1;
        self.order.insert((self.clock, key.clone()));
        self.entries.insert(
            key,
            Entry {
                value,
                tick: self.clock,
            },
        );
    }
}
pub struct EnglishStems {
    provider: Arc<dyn WordStemmer>,
    cache: Mutex<Cache>,
}
impl EnglishStems {
    pub fn shared() -> Arc<Self> {
        static SHARED: OnceLock<Arc<EnglishStems>> = OnceLock::new();
        SHARED
            .get_or_init(|| Arc::new(Self::with_provider(Arc::new(EnglishAlgorithm))))
            .clone()
    }
    /// An explicit provider owns a separate cache; replacing a provider never
    /// reuses the words of another implementation with an equal advertised spec.
    pub fn with_provider(provider: Arc<dyn WordStemmer>) -> Self {
        Self {
            provider,
            cache: Mutex::new(Cache::default()),
        }
    }
    pub fn stem_words(&self, words: &[PythonText]) -> Result<Vec<PythonText>> {
        words.iter().map(|word| self.stem(word)).collect()
    }
    pub fn cached_words(&self) -> usize {
        self.cache.lock().expect("English cache").entries.len()
    }
}
impl WordStemmer for EnglishStems {
    fn stem(&self, word: &PythonText) -> Result<PythonText> {
        let cacheable = word.codepoints().len() <= MAX_CACHED_POINTS;
        if cacheable
            && let Some(value) = self
                .cache
                .lock()
                .expect("English cache")
                .get(word.codepoints())
        {
            return Ok(value);
        }
        let value = self.provider.stem(word)?;
        if cacheable {
            self.cache
                .lock()
                .expect("English cache")
                .insert(word.codepoints().to_vec(), value.clone());
        }
        Ok(value)
    }
}
