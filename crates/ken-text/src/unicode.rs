//! Python's frozen Unicode 15 character properties, independent of Rust's version.
use serde::Deserialize;
use std::{collections::BTreeMap, sync::OnceLock};
#[derive(Deserialize)]
struct Unicode {
    word_ranges: Vec<[u32; 2]>,
    decimal_ranges: Vec<[u32; 2]>,
    casefold: BTreeMap<String, String>,
}
fn table() -> &'static Unicode {
    static TABLE: OnceLock<Unicode> = OnceLock::new();
    TABLE.get_or_init(|| {
        serde_json::from_str(include_str!("unicode15.json")).expect("frozen Unicode15 data")
    })
}
fn contains(ranges: &[[u32; 2]], c: char) -> bool {
    let code = u32::from(c);
    ranges
        .get(ranges.partition_point(|r| r[1] < code))
        .is_some_and(|r| r[0] <= code)
}
pub fn word(c: char) -> bool {
    contains(&table().word_ranges, c)
}
pub fn decimal(c: char) -> bool {
    contains(&table().decimal_ranges, c)
}
#[derive(Deserialize)]
struct QueryUnicode {
    identifier_start: Vec<[u32; 2]>,
    identifier_continue: Vec<[u32; 2]>,
    query_literal_fold: BTreeMap<String, String>,
}
fn query_table() -> &'static QueryUnicode {
    static TABLE: OnceLock<QueryUnicode> = OnceLock::new();
    TABLE.get_or_init(|| {
        serde_json::from_str(include_str!("query_unicode15.json")).expect("frozen query Unicode15")
    })
}
pub fn identifier(text: &str) -> bool {
    let mut chars = text.chars();
    chars
        .next()
        .is_some_and(|c| contains(&query_table().identifier_start, c))
        && chars.all(|c| contains(&query_table().identifier_continue, c))
}
/// Single-character equivalences for the ASCII/Spanish literals of query patterns.
pub fn query_literal_fold(c: char) -> char {
    query_table()
        .query_literal_fold
        .get(&u32::from(c).to_string())
        .and_then(|s| s.chars().next())
        .unwrap_or(c)
}
/// Unicode15 word ranges as literal regex character-class content.
pub fn word_class_content() -> String {
    let mut result = String::new();
    for &[start, end] in &table().word_ranges {
        result.push(char::from_u32(start).expect("word scalar"));
        if end != start {
            result.push('-');
            result.push(char::from_u32(end).expect("word scalar"));
        }
    }
    result
}
pub fn whitespace(c: char) -> bool {
    c.is_whitespace() || matches!(c, '\x1c'..='\x1f')
}
pub fn casefold(text: &str) -> String {
    let mut result = String::new();
    for c in text.chars() {
        if let Some(s) = table().casefold.get(&u32::from(c).to_string()) {
            result.push_str(s)
        } else {
            result.push(c)
        }
    }
    result
}
/// Python str.splitlines, including CRLF as one boundary and no trailing empty line.
pub fn splitlines(text: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut it = text.char_indices().peekable();
    while let Some((i, c)) = it.next() {
        if matches!(
            c,
            '\n' | '\r' | '\x0b' | '\x0c' | '\x1c'..='\x1e' | '\u{85}' | '\u{2028}' | '\u{2029}'
        ) {
            out.push(&text[start..i]);
            start = i + c.len_utf8();
            if c == '\r' && it.peek().is_some_and(|(_, c)| *c == '\n') {
                let (j, c) = it.next().unwrap();
                start = j + c.len_utf8();
            }
        }
    }
    if start < text.len() {
        out.push(&text[start..]);
    }
    out
}

/// Decimal value from the frozen Nd blocks, including adjacent ten-digit scripts.
pub fn decimal_digit(c: char) -> Option<u32> {
    let code = u32::from(c);
    let ranges = &table().decimal_ranges;
    ranges
        .get(ranges.partition_point(|r| r[1] < code))
        .filter(|r| r[0] <= code)
        .map(|r| (code - r[0]) % 10)
}
