//! Ordered config values retain Python JSON's numeric and string tolerance.
use regex::Regex;
use serde_json::value::RawValue;
use std::sync::OnceLock;
#[derive(Clone, Debug)]
pub(super) enum ConfigValue {
    Object(Vec<(Option<String>, ConfigValue)>),
    Array(Vec<ConfigValue>),
    Text(Option<String>),
    Other { truth: bool },
    Null,
}
impl ConfigValue {
    pub fn get(&self, key: &str) -> Option<&Self> {
        self.object()?
            .iter()
            .find(|(k, _)| k.as_deref() == Some(key))
            .map(|(_, v)| v)
    }
    pub fn object(&self) -> Option<&[(Option<String>, Self)]> {
        if let Self::Object(values) = self {
            Some(values)
        } else {
            None
        }
    }
    pub fn text(&self) -> Option<&str> {
        if let Self::Text(value) = self {
            value.as_deref()
        } else {
            None
        }
    }
    pub fn truth(&self) -> bool {
        match self {
            Self::Object(v) => !v.is_empty(),
            Self::Array(v) => !v.is_empty(),
            Self::Text(v) => v.as_ref().is_none_or(|s| !s.is_empty()),
            Self::Other { truth } => *truth,
            Self::Null => false,
        }
    }
    pub fn is_null(&self) -> bool {
        matches!(self, Self::Null)
    }
}
pub(super) fn jsonc(bytes: &[u8]) -> Option<ConfigValue> {
    let text = String::from_utf8_lossy(bytes);
    let source = text.as_bytes();
    let mut output = Vec::new();
    let mut i = 0;
    let mut quoted = false;
    let mut escaped = false;
    while i < source.len() {
        let c = source[i];
        if quoted {
            output.push(c);
            if escaped {
                escaped = false;
            } else if c == b'\\' {
                escaped = true;
            } else if c == b'"' {
                quoted = false;
            }
            i += 1;
            continue;
        }
        if c == b'"' {
            quoted = true;
            output.push(c);
            i += 1;
            continue;
        }
        if source.get(i..i + 2) == Some(b"//") {
            while i < source.len() && source[i] != b'\n' {
                i += 1;
            }
        } else if source.get(i..i + 2) == Some(b"/*") {
            i += 2;
            while i + 1 < source.len() && source.get(i..i + 2) != Some(b"*/") {
                i += 1;
            }
            i += 2;
        } else {
            output.push(c);
            i += 1;
        }
    }
    let stripped = String::from_utf8(output).ok()?;
    static TRAILING: OnceLock<Regex> = OnceLock::new();
    let cleaned = TRAILING
        .get_or_init(|| Regex::new(r",([\s\x1c-\x1f]*[}\]])").expect("static JSONC expression"))
        .replace_all(&stripped, "$1");
    parse(&cleaned)
}
pub(super) fn parse(text: &str) -> Option<ConfigValue> {
    let mut parser = Parser { text, position: 0 };
    let value = parser.value(0)?;
    parser.whitespace();
    (parser.position == text.len()).then_some(value)
}
struct Parser<'a> {
    text: &'a str,
    position: usize,
}
impl Parser<'_> {
    fn whitespace(&mut self) {
        while self
            .text
            .as_bytes()
            .get(self.position)
            .is_some_and(|c| matches!(c, b' ' | b'\t' | b'\r' | b'\n'))
        {
            self.position += 1;
        }
    }
    fn consume(&mut self, byte: u8) -> bool {
        self.whitespace();
        if self.text.as_bytes().get(self.position) != Some(&byte) {
            return false;
        }
        self.position += 1;
        true
    }
    fn string(&mut self) -> Option<Option<String>> {
        self.whitespace();
        let start = self.position;
        if !self.consume(b'"') {
            return None;
        }
        while let Some(&byte) = self.text.as_bytes().get(self.position) {
            self.position += 1;
            if byte == b'\\' {
                self.position += 1;
            } else if byte == b'"' {
                let raw = &self.text[start..self.position];
                serde_json::from_str::<Box<RawValue>>(raw).ok()?;
                // A non-scalar Python string cannot match a UTF8 inventory path,
                // but an unrelated config field must not invalidate other keys.
                return Some(serde_json::from_str(raw).ok());
            }
        }
        None
    }
    fn value(&mut self, depth: usize) -> Option<ConfigValue> {
        if depth > 1000 {
            return None;
        }
        self.whitespace();
        match *self.text.as_bytes().get(self.position)? {
            b'"' => return Some(ConfigValue::Text(self.string()?)),
            b'{' => {
                self.position += 1;
                let mut values: Vec<(Option<String>, ConfigValue)> = Vec::new();
                if self.consume(b'}') {
                    return Some(ConfigValue::Object(values));
                }
                loop {
                    let key = self.string()?;
                    if !self.consume(b':') {
                        return None;
                    }
                    let value = self.value(depth + 1)?;
                    if let Some(existing) = key
                        .as_ref()
                        .and_then(|key| values.iter_mut().find(|(k, _)| k.as_ref() == Some(key)))
                    {
                        existing.1 = value;
                    } else {
                        values.push((key, value));
                    }
                    if self.consume(b'}') {
                        break;
                    }
                    if !self.consume(b',') {
                        return None;
                    }
                }
                return Some(ConfigValue::Object(values));
            }
            b'[' => {
                self.position += 1;
                let mut values = Vec::new();
                if self.consume(b']') {
                    return Some(ConfigValue::Array(values));
                }
                loop {
                    values.push(self.value(depth + 1)?);
                    if self.consume(b']') {
                        break;
                    }
                    if !self.consume(b',') {
                        return None;
                    }
                }
                return Some(ConfigValue::Array(values));
            }
            _ => {}
        }
        let start = self.position;
        while self
            .text
            .as_bytes()
            .get(self.position)
            .is_some_and(|c| !matches!(c, b' ' | b'\t' | b'\r' | b'\n' | b',' | b']' | b'}'))
        {
            self.position += 1;
        }
        let raw = &self.text[start..self.position];
        match raw {
            "null" => Some(ConfigValue::Null),
            "true" => Some(ConfigValue::Other { truth: true }),
            "false" => Some(ConfigValue::Other { truth: false }),
            "NaN" | "Infinity" | "-Infinity" => Some(ConfigValue::Other { truth: true }),
            _ => {
                serde_json::from_str::<Box<RawValue>>(raw).ok()?;
                let number: f64 = raw.parse().ok()?;
                Some(ConfigValue::Other {
                    truth: number != 0.0,
                })
            }
        }
    }
}
