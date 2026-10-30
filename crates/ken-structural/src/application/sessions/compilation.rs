//! Exact-input bounded plan reuse. No query outcomes enter this cache.
use super::*;
use ken_query::{BackendPreference, ParseLimits, compile, parse};
use std::{
    collections::VecDeque,
    io::{self, Write},
};
/// Count serialized plan bytes without a second plan-sized allocation.
#[derive(Default)]
struct PlanBytes(usize);
impl Write for PlanBytes {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.0 = self.0.saturating_add(bytes.len());
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
#[derive(Clone, PartialEq, Eq)]
struct Key {
    source: String,
    query: Option<String>,
    libraries: BTreeMap<String, String>,
    reference: bool,
}
struct Entry {
    key: Key,
    compiled: Arc<CompiledQuery>,
    bytes: usize,
}
pub(super) struct CompilationCache {
    entries: VecDeque<Entry>,
    bytes: usize,
    budget: usize,
    evictions: u64,
}
impl CompilationCache {
    pub fn new(budget: usize) -> Self {
        Self {
            entries: VecDeque::new(),
            bytes: 0,
            budget,
            evictions: 0,
        }
    }
    pub fn clear(&mut self) {
        self.entries.clear();
        self.bytes = 0;
    }
    fn metadata(&self, status: &str) -> Json {
        json!({"status":status,"bytes":self.bytes,"budget_bytes":self.budget,"entries":self.entries.len(),"evictions":self.evictions,"backend":"native_memory","accounting":"serialized_key_and_plan_bytes"})
    }
    pub fn compile(
        &mut self,
        resolved: &ResolvedQuery,
        reference: bool,
    ) -> Result<(Arc<CompiledQuery>, Json)> {
        let key = Key {
            source: resolved.source.clone(),
            query: resolved.query_name.clone(),
            libraries: resolved.libraries().clone(),
            reference,
        };
        if let Some(position) = self.entries.iter().position(|entry| entry.key == key) {
            let entry = self.entries.remove(position).unwrap();
            let compiled = entry.compiled.clone();
            self.entries.push_back(entry);
            return Ok((compiled, self.metadata("memory")));
        }
        let tree = parse(&key.source, "<query>", ParseLimits::default())?;
        let libraries = key
            .libraries
            .iter()
            .map(|(name, source)| Ok((name.clone(), parse(source, name, ParseLimits::default())?)))
            .collect::<std::result::Result<BTreeMap<_, _>, ParseError>>()?;
        let compiled = Arc::new(compile(
            &tree,
            key.query.as_deref(),
            &libraries,
            BackendPreference::Automatic,
        )?);
        let mut plan_bytes = PlanBytes::default();
        serde_json::to_writer(&mut plan_bytes, compiled.as_ref())?;
        let bytes = key.libraries.iter().fold(
            plan_bytes
                .0
                .saturating_add(key.source.len())
                .saturating_add(key.query.as_ref().map_or(0, String::len))
                .saturating_add(1),
            |bytes, (name, source)| {
                bytes
                    .saturating_add(name.len())
                    .saturating_add(source.len())
            },
        );
        if bytes <= self.budget {
            while self.bytes.saturating_add(bytes) > self.budget {
                let Some(old) = self.entries.pop_front() else {
                    break;
                };
                self.bytes = self.bytes.saturating_sub(old.bytes);
                self.evictions = self.evictions.saturating_add(1);
            }
            self.bytes = self.bytes.saturating_add(bytes);
            self.entries.push_back(Entry {
                key,
                compiled: compiled.clone(),
                bytes,
            });
        }
        Ok((compiled, self.metadata("miss")))
    }
}
