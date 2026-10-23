//! Ordered native parsing, without sharing SQLite or model encoders with workers.
use ken_syntax::{Language, ParsedFile, ParserRegistry};
pub struct ParseJob {
    pub language: Language,
    pub path: String,
    pub bytes: Vec<u8>,
}
fn override_count(value: &str) -> Option<usize> {
    let text = value.trim_matches(ken_text::unicode::whitespace);
    let (negative, text) = if let Some(s) = text.strip_prefix('-') {
        (true, s)
    } else {
        (false, text.strip_prefix('+').unwrap_or(text))
    };
    if text.is_empty() {
        return None;
    }
    let mut count = 0usize;
    let mut previous_digit = false;
    for c in text.chars() {
        if c == '_' {
            if !previous_digit {
                return None;
            }
            previous_digit = false;
            continue;
        }
        let digit = ken_text::unicode::decimal_digit(c)?;
        count = count.saturating_mul(10).saturating_add(digit as usize);
        previous_digit = true;
    }
    previous_digit.then_some(if negative { 0 } else { count })
}
pub fn worker_count(n_files: usize, cpus: usize, override_value: Option<&str>) -> usize {
    if let Some(count) = override_value.and_then(override_count) {
        return count;
    }
    if n_files < 64 || cpus < 2 {
        return 0;
    }
    8.min(cpus - 1).min(2.max(n_files / 32))
}
fn parse(registry: &ParserRegistry, job: &ParseJob) -> Option<ParsedFile> {
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        registry.parse(job.language, &job.bytes, &job.path)
    }))
    .ok()
    .and_then(std::result::Result::ok)
}
pub fn parse_all(
    registry: &ParserRegistry,
    jobs: &[ParseJob],
    workers: usize,
) -> Vec<Option<ParsedFile>> {
    let serial = || jobs.iter().map(|job| parse(registry, job)).collect();
    if workers == 0 || jobs.len() < 2 {
        return serial();
    }
    let chunks = jobs.len().div_ceil(workers.min(jobs.len()));
    let result = std::thread::scope(|scope| {
        let mut handles = Vec::new();
        let mut failed = false;
        for jobs in jobs.chunks(chunks) {
            match std::thread::Builder::new().spawn_scoped(scope, move || {
                jobs.iter()
                    .map(|job| parse(registry, job))
                    .collect::<Vec<_>>()
            }) {
                Ok(handle) => handles.push(handle),
                Err(_) => {
                    failed = true;
                    break;
                }
            }
        }
        let mut out = Vec::new();
        for handle in handles {
            match handle.join() {
                Ok(rows) => out.extend(rows),
                Err(_) => failed = true,
            }
        }
        if failed { None } else { Some(out) }
    });
    result.unwrap_or_else(serial)
}
