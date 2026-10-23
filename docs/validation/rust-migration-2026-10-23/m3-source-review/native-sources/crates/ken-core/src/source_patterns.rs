// SPDX-License-Identifier: MPL-2.0
// Adapted from pathspec 1.1.1's GitIgnoreSpecPattern and SimpleGiBackend,
// by Caleb P. Burns and pathspec contributors. Modified for native Rust by Ken.
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. A copy is in licenses/pathspec-MPL-2.0.txt.
//! Character-based pathspec compatibility; no traversal or rule-file ownership.
use regex::Regex;

#[derive(Default)]
pub(crate) struct SourcePatterns(Vec<Pattern>);
struct Pattern {
    regex: Regex,
    ignored: bool,
}

impl SourcePatterns {
    pub(crate) fn compile(text: &str) -> Result<Self, String> {
        let mut patterns = Vec::new();
        // Python str.splitlines(), including the Unicode/control separators.
        for line in text.split(|c| {
            matches!(
                c,
                '\n' | '\r'
                    | '\x0b'
                    | '\x0c'
                    | '\x1c'
                    | '\x1d'
                    | '\x1e'
                    | '\u{85}'
                    | '\u{2028}'
                    | '\u{2029}'
            )
        }) {
            if let Some(pattern) = Pattern::compile(line)? {
                patterns.push(pattern);
            }
        }
        Ok(Self(patterns))
    }

    pub(crate) fn decision(&self, path: &str) -> Option<bool> {
        let mut directory_match = None;
        // The last exact-file match outranks all ancestor-directory matches.
        for pattern in self.0.iter().rev() {
            if let Some(captures) = pattern.regex.captures(path) {
                if captures.name("directory").is_none() {
                    return Some(pattern.ignored);
                }
                if directory_match.is_none() {
                    directory_match = Some(pattern.ignored);
                }
            }
        }
        directory_match
    }
}

const DIRECTORY: &str = "(?P<directory>/)";
// Python '$' also matches just before a final newline.
const END: &str = "(?:(?P<directory>/)|\\n?\\z)";

impl Pattern {
    fn compile(line: &str) -> Result<Option<Self>, String> {
        let line = if line.ends_with("\\ ") {
            line
        } else {
            line.trim_end_matches(|c: char| c.is_whitespace() || matches!(c, '\x1c'..='\x1f'))
        };
        if line.is_empty() || line.starts_with('#') || line == "/" {
            return Ok(None);
        }
        let (ignored, line) = match line.strip_prefix('!') {
            Some(line) => (false, line),
            None => (true, line),
        };
        if line.is_empty() {
            return Err("negation has no pattern".into());
        }
        let directory = line.ends_with('/');
        let mut segments: Vec<_> = line.split('/').collect();
        if segments[0].is_empty() {
            segments.remove(0);
        } else if (segments.len() == 1 || (segments.len() == 2 && directory)) && segments[0] != "**"
        {
            segments.insert(0, "**");
        }
        if let Some(last) = segments.last_mut().filter(|s| s.is_empty()) {
            *last = "**";
        }
        segments.dedup_by(|a, b| *a == "**" && *b == "**");
        let expression = match segments.as_slice() {
            ["**"] if directory => DIRECTORY.into(),
            ["**"] | ["**", "*"] => ".".into(),
            ["**", "*", "**"] if directory => DIRECTORY.into(),
            ["**", "*", "**"] => "/".into(),
            _ => match translate(&segments, directory)? {
                Some(expression) => expression,
                None => return Ok(None), // unclosed class, the original's sole range-noop
            },
        };
        Ok(Some(Self {
            regex: Regex::new(&expression).map_err(|error| format!("{line:?}: {error}"))?,
            ignored,
        }))
    }
}

fn translate(segments: &[&str], directory: bool) -> Result<Option<String>, String> {
    let mut expression = String::new();
    let mut slash = false;
    for (index, segment) in segments.iter().enumerate() {
        let last = index + 1 == segments.len();
        if *segment == "**" {
            if index == 0 {
                expression.push_str("^(?:.+/)?");
            } else if !last {
                expression.push_str("(?:/.+)?");
                slash = true;
            } else {
                expression.push_str(if directory { DIRECTORY } else { "/" });
            }
        } else {
            if index == 0 {
                expression.push('^');
            }
            if slash {
                expression.push('/');
            }
            if *segment == "*" {
                expression.push_str("[^/]+");
            } else if let Some(glob) = segment_glob(segment)? {
                expression.push_str(&glob);
            } else {
                return Ok(None);
            }
            if last {
                expression.push_str(END);
            }
            slash = true;
        }
    }
    Ok(Some(expression))
}

fn segment_glob(segment: &str) -> Result<Option<String>, String> {
    let chars: Vec<_> = segment.chars().collect();
    let mut out = String::new();
    let mut index = 0;
    while index < chars.len() {
        let ch = chars[index];
        index += 1;
        match ch {
            '\\' => {
                let literal = chars.get(index).ok_or("dangling escape")?;
                out.push_str(&regex::escape(&literal.to_string()));
                index += 1;
            }
            '*' => out.push_str("[^/]*"),
            '?' => out.push_str("[^/]"),
            '[' => {
                let start = index;
                let negated = chars.get(index).is_some_and(|c| matches!(c, '!' | '^'));
                let body_start = start + usize::from(negated);
                let mut end = body_start;
                if chars.get(end) == Some(&']') {
                    end += 1;
                }
                while end < chars.len() && chars[end] != ']' {
                    end += 1;
                }
                if end == chars.len() {
                    return Ok(None);
                }
                out.push('[');
                if negated {
                    out.push('^');
                }
                // Parse ranges before emitting regex syntax. Python rejects a--b;
                // Rust otherwise treats -- as set difference and accepts it.
                let mut item = body_start;
                while item < end {
                    let first = chars[item];
                    item += 1;
                    class_literal(&mut out, first);
                    if item + 1 < end && chars[item] == '-' {
                        let last = chars[item + 1];
                        if first > last {
                            return Err(format!("descending character range {first}-{last}"));
                        }
                        out.push('-');
                        class_literal(&mut out, last);
                        item += 2;
                    }
                }
                out.push(']');
                index = end + 1;
            }
            _ => out.push_str(&regex::escape(&ch.to_string())),
        }
    }
    Ok(Some(out))
}

fn class_literal(out: &mut String, literal: char) {
    if matches!(literal, '\\' | '[' | ']' | '&' | '~' | '^' | '-') {
        out.push('\\');
    }
    out.push(literal);
}
