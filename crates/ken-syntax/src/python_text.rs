//! Python text admits surrogate code points that Rust scalar strings cannot hold.
use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error};
use serde_json::value::RawValue;

/// Lossless Python code points. JSON preserves isolated surrogates as escapes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PythonText {
    codepoints: Vec<u32>,
}
impl PythonText {
    pub fn from_codepoints(codepoints: Vec<u32>) -> Option<Self> {
        codepoints
            .iter()
            .all(|c| *c <= 0x10ffff)
            .then_some(Self { codepoints })
    }
    pub fn codepoints(&self) -> &[u32] {
        &self.codepoints
    }
    pub fn to_utf8(&self) -> Option<String> {
        self.codepoints.iter().map(|&c| char::from_u32(c)).collect()
    }
    pub(crate) fn trimmed(mut self) -> Self {
        let whitespace = |c: &u32| char::from_u32(*c).is_some_and(crate::helpers::whitespace);
        let start = self
            .codepoints
            .iter()
            .position(|c| !whitespace(c))
            .unwrap_or(self.codepoints.len());
        let end = self
            .codepoints
            .iter()
            .rposition(|c| !whitespace(c))
            .map_or(start, |i| i + 1);
        self.codepoints = self.codepoints[start..end].to_vec();
        self
    }
    pub fn is_empty(&self) -> bool {
        self.codepoints.is_empty()
    }
}
impl From<String> for PythonText {
    fn from(value: String) -> Self {
        Self {
            codepoints: value.chars().map(u32::from).collect(),
        }
    }
}
impl From<&str> for PythonText {
    fn from(value: &str) -> Self {
        Self {
            codepoints: value.chars().map(u32::from).collect(),
        }
    }
}
impl Serialize for PythonText {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        let mut json = String::from("\"");
        for &point in &self.codepoints {
            match point {
                0x22 => json.push_str("\\\""),
                0x5c => json.push_str("\\\\"),
                0..=0x1f | 0xd800..=0xdfff => json.push_str(&format!("\\u{point:04x}")),
                _ => json.push(char::from_u32(point).expect("validated Python code point")),
            }
        }
        json.push('"');
        RawValue::from_string(json)
            .map_err(serde::ser::Error::custom)?
            .serialize(serializer)
    }
}
impl<'de> Deserialize<'de> for PythonText {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        // Capture before scalar-string decoding rejects an isolated surrogate.
        let raw = Box::<RawValue>::deserialize(deserializer)?;
        let raw = raw.get();
        let inner = raw
            .strip_prefix('"')
            .and_then(|s| s.strip_suffix('"'))
            .ok_or_else(|| D::Error::custom("Python text requires a JSON string"))?;
        let mut chars = inner.chars();
        let mut points = Vec::new();
        while let Some(character) = chars.next() {
            let point = if character != '\\' {
                character as u32
            } else {
                match chars
                    .next()
                    .ok_or_else(|| D::Error::custom("incomplete JSON escape"))?
                {
                    'u' => {
                        let hex: String = chars.by_ref().take(4).collect();
                        if hex.len() != 4 {
                            return Err(D::Error::custom("incomplete Unicode escape"));
                        }
                        u32::from_str_radix(&hex, 16).map_err(D::Error::custom)?
                    }
                    '"' => 0x22,
                    '\\' => 0x5c,
                    '/' => 0x2f,
                    'b' => 8,
                    'f' => 12,
                    'n' => 10,
                    'r' => 13,
                    't' => 9,
                    _ => return Err(D::Error::custom("invalid JSON escape")),
                }
            };
            points.push(point);
        }
        Ok(Self { codepoints: points })
    }
}
