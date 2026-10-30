//! String-aware JSONC admission and minimal object insertion. Original comments
//! and string bytes survive host installation; no regex rewrites quoted text.
use crate::{Result, invalid};
use serde_json::Value;
fn cleaned(text: &str) -> Result<String> {
    let bytes = text.as_bytes();
    let mut out = bytes.to_vec();
    let mut at = 0;
    let mut string = false;
    let mut escape = false;
    while at < bytes.len() {
        let c = bytes[at];
        if string {
            if escape {
                escape = false;
            } else if c == b'\\' {
                escape = true;
            } else if c == b'"' {
                string = false;
            }
            at += 1;
            continue;
        }
        if c == b'"' {
            string = true;
            at += 1;
            continue;
        }
        if c == b'/' && bytes.get(at + 1) == Some(&b'/') {
            while at < bytes.len() && bytes[at] != b'\n' {
                out[at] = b' ';
                at += 1;
            }
            continue;
        }
        if c == b'/' && bytes.get(at + 1) == Some(&b'*') {
            let start = at;
            at += 2;
            while at + 1 < bytes.len() && &bytes[at..at + 2] != b"*/" {
                at += 1;
            }
            if at + 1 >= bytes.len() {
                return Err(invalid("unterminated JSONC block comment"));
            }
            at += 2;
            for i in start..at {
                if !matches!(bytes[i], b'\n' | b'\r') {
                    out[i] = b' ';
                }
            }
            continue;
        }
        at += 1;
    }
    let mut at = 0;
    string = false;
    escape = false;
    while at < out.len() {
        let c = out[at];
        if string {
            if escape {
                escape = false;
            } else if c == b'\\' {
                escape = true;
            } else if c == b'"' {
                string = false;
            }
        } else if c == b'"' {
            string = true;
        } else if c == b',' {
            let mut next = at + 1;
            while next < out.len() && out[next].is_ascii_whitespace() {
                next += 1;
            }
            if out.get(next).is_some_and(|c| matches!(*c, b'}' | b']')) {
                out[at] = b' ';
            }
        }
        at += 1;
    }
    String::from_utf8(out).map_err(|_| invalid("invalid JSONC UTF8"))
}
pub fn parse(text: &str) -> Result<Value> {
    let clean = cleaned(text)?;
    let value = serde_json::from_str(&clean)?;
    Cursor {
        text: &clean,
        at: 0,
    }
    .value()?;
    Ok(value)
}
#[derive(Debug)]
struct Span {
    start: usize,
    end: usize,
    object: Option<Vec<(String, Span)>>,
}
struct Cursor<'a> {
    text: &'a str,
    at: usize,
}
impl Cursor<'_> {
    fn whitespace(&mut self) {
        while self
            .text
            .as_bytes()
            .get(self.at)
            .is_some_and(u8::is_ascii_whitespace)
        {
            self.at += 1;
        }
    }
    fn string(&mut self) -> Result<(String, usize)> {
        let start = self.at;
        self.at += 1;
        while self.at < self.text.len() {
            match self.text.as_bytes()[self.at] {
                b'\\' => self.at += 2,
                b'"' => {
                    self.at += 1;
                    return Ok((serde_json::from_str(&self.text[start..self.at])?, self.at));
                }
                _ => self.at += 1,
            }
        }
        Err(invalid("incomplete JSONC string"))
    }
    fn value(&mut self) -> Result<Span> {
        self.whitespace();
        let start = self.at;
        let c = *self
            .text
            .as_bytes()
            .get(self.at)
            .ok_or_else(|| invalid("incomplete JSONC value"))?;
        let mut object = None;
        match c {
            b'{' => {
                self.at += 1;
                let mut entries = Vec::new();
                loop {
                    self.whitespace();
                    if self.text.as_bytes().get(self.at) == Some(&b'}') {
                        self.at += 1;
                        break;
                    }
                    if self.text.as_bytes().get(self.at) != Some(&b'"') {
                        return Err(invalid("invalid JSONC object key"));
                    }
                    let (key, _) = self.string()?;
                    if entries.iter().any(|(old, _)| old == &key) {
                        return Err(invalid("ambiguous duplicate JSONC object key"));
                    }
                    self.whitespace();
                    if self.text.as_bytes().get(self.at) != Some(&b':') {
                        return Err(invalid("missing JSONC colon"));
                    }
                    self.at += 1;
                    let value = self.value()?;
                    entries.push((key, value));
                    self.whitespace();
                    match self.text.as_bytes().get(self.at) {
                        Some(b',') => self.at += 1,
                        Some(b'}') => {
                            self.at += 1;
                            break;
                        }
                        _ => return Err(invalid("incomplete JSONC object")),
                    }
                }
                object = Some(entries);
            }
            b'[' => {
                self.at += 1;
                loop {
                    self.whitespace();
                    if self.text.as_bytes().get(self.at) == Some(&b']') {
                        self.at += 1;
                        break;
                    }
                    self.value()?;
                    self.whitespace();
                    match self.text.as_bytes().get(self.at) {
                        Some(b',') => self.at += 1,
                        Some(b']') => {
                            self.at += 1;
                            break;
                        }
                        _ => return Err(invalid("incomplete JSONC array")),
                    }
                }
            }
            b'"' => {
                self.string()?;
            }
            _ => {
                while self
                    .text
                    .as_bytes()
                    .get(self.at)
                    .is_some_and(|c| !c.is_ascii_whitespace() && !matches!(*c, b',' | b'}' | b']'))
                {
                    self.at += 1;
                }
            }
        }
        Ok(Span {
            start,
            end: self.at,
            object,
        })
    }
}
pub(crate) fn insert(text: &str, path: &[&str], key: &str, value: &Value) -> Result<String> {
    parse(text)?;
    let clean = cleaned(text)?;
    let mut cursor = Cursor {
        text: &clean,
        at: 0,
    };
    let root = cursor.value()?;
    let mut target = &root;
    for key in path {
        target = &target
            .object
            .as_ref()
            .ok_or_else(|| invalid("host configuration section must be an object"))?
            .iter()
            .find(|(k, _)| k == key)
            .ok_or_else(|| invalid("host configuration section is missing"))?
            .1;
    }
    let entries = target
        .object
        .as_ref()
        .ok_or_else(|| invalid("host configuration section must be an object"))?;
    if entries.iter().any(|(k, _)| k == key) {
        return Err(invalid("JSONC managed key already exists"));
    }
    let (at, separator) = entries
        .last()
        .map_or((target.start + 1, ""), |(_, last)| (last.end, ","));
    let addition = format!(
        "{separator}\n  {}: {}",
        serde_json::to_string(key)?,
        serde_json::to_string(value)?
    );
    let mut output = String::with_capacity(text.len() + addition.len());
    output.push_str(&text[..at]);
    output.push_str(&addition);
    output.push_str(&text[at..]);
    parse(&output)?;
    Ok(output)
}
