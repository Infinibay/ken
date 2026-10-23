//! Bounded purpose text from shallow project text files.
use ken_text::unicode::{splitlines, whitespace};
pub fn collapse(text: &str) -> String {
    text.split(whitespace)
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}
fn trimmed(text: &str) -> &str {
    text.trim_matches(whitespace)
}
fn truncate(text: &str, limit: usize) -> String {
    text.chars().take(limit).collect()
}
fn decode_ignoring_errors(mut source: &[u8]) -> String {
    let mut text = String::new();
    while !source.is_empty() {
        match std::str::from_utf8(source) {
            Ok(s) => {
                text.push_str(s);
                break;
            }
            Err(e) => {
                text.push_str(
                    std::str::from_utf8(&source[..e.valid_up_to()]).expect("valid prefix"),
                );
                let Some(size) = e.error_len() else { break };
                source = &source[e.valid_up_to() + size..];
            }
        }
    }
    text
}
pub fn stem(path: &str) -> &str {
    let name = path.rsplit('/').next().unwrap_or("");
    match name.rfind('.') {
        Some(i) if i > 0 && i + 1 < name.len() => &name[..i],
        _ => name,
    }
}
fn suffix(path: &str) -> String {
    let name = path.rsplit('/').next().unwrap_or("");
    match name.rfind('.') {
        Some(i) if i > 0 && i + 1 < name.len() => name[i..].to_lowercase(),
        _ => String::new(),
    }
}
pub fn plain_text_intents(path: &str, source: &[u8]) -> Vec<String> {
    let suffix = suffix(path);
    if !matches!(
        suffix.as_str(),
        ".md" | ".rst" | ".txt" | ".sh" | ".toml" | ".json" | ".jsonl" | ".yaml" | ".yml"
    ) || path
        .split('/')
        .filter(|s| !s.is_empty() && *s != ".")
        .count()
        > 2
    {
        return vec![];
    }
    let text = decode_ignoring_errors(source);
    if matches!(suffix.as_str(), ".md" | ".rst") {
        let mut chunks = Vec::new();
        let mut current = Vec::new();
        let append = |chunks: &mut Vec<String>, lines: &mut Vec<&str>| {
            let s = collapse(&lines.join(" "));
            if !s.is_empty() {
                chunks.push(truncate(&s, 1200))
            }
            lines.clear();
        };
        for line in splitlines(&text) {
            let line = trimmed(line);
            if line.starts_with('#') && !current.is_empty() {
                append(&mut chunks, &mut current)
            }
            if !line.is_empty() {
                current.push(trimmed(line.trim_start_matches('#')));
            }
        }
        append(&mut chunks, &mut current);
        chunks.truncate(8);
        return chunks;
    }
    let mut lines = Vec::new();
    let mut chars = 0;
    for line in splitlines(&text) {
        let line = trimmed(line);
        if line.is_empty()
            || line.starts_with("<!--")
            || line.starts_with("//")
            || (suffix == ".sh" && line.starts_with('#') && !line.starts_with("#!"))
            || (matches!(suffix.as_str(), ".json" | ".jsonl")
                && matches!(line, "{" | "}" | "[" | "]"))
        {
            continue;
        }
        let line = trimmed(line.trim_start_matches('#'));
        lines.push(line);
        chars += line.chars().count();
        if chars >= 4000 {
            break;
        }
    }
    if lines.is_empty() {
        vec![]
    } else {
        vec![truncate(&collapse(&lines.join(" ")), 4000)]
    }
}
