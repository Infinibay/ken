use std::collections::HashMap;

const MAX_BYTES: usize = 8 * 1024 * 1024;
const MAX_ENTRIES: usize = 8192;

struct Entry {
    value: Vec<f32>,
    used: u128,
}

/// Bounded short-term memoization. Returned values always own an independent copy.
#[derive(Default)]
pub(crate) struct TermCache {
    entries: HashMap<String, Entry>,
    bytes: usize,
    clock: u128,
}

fn eligible(text: &str) -> bool {
    !text.is_empty()
        && text.chars().count() <= 128
        && !text
            .chars()
            .any(|c| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c))
}

fn cost(text: &str, value: &[f32]) -> usize {
    value.len() * 4 + text.len() + 256
}

impl TermCache {
    pub fn get(&mut self, text: &str) -> Option<Vec<f32>> {
        if !eligible(text) {
            return None;
        }
        let entry = self.entries.get_mut(text)?;
        self.clock += 1;
        entry.used = self.clock;
        Some(entry.value.clone())
    }

    pub fn insert(&mut self, text: &str, value: &[f32]) {
        if !eligible(text) {
            return;
        }
        let size = cost(text, value);
        if size > MAX_BYTES {
            return;
        }
        if let Some(old) = self.entries.remove(text) {
            self.bytes -= cost(text, &old.value);
        }
        self.clock += 1;
        self.entries.insert(
            text.into(),
            Entry {
                value: value.to_vec(),
                used: self.clock,
            },
        );
        self.bytes += size;
        while self.bytes > MAX_BYTES || self.entries.len() > MAX_ENTRIES {
            let key = self
                .entries
                .iter()
                .min_by_key(|(_, entry)| entry.used)
                .expect("over-budget cache has entries")
                .0
                .clone();
            let old = self
                .entries
                .remove(&key)
                .expect("selected cache entry exists");
            self.bytes -= cost(&key, &old.value);
        }
    }
}
