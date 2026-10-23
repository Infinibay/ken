//! Ordered config values retain Python JSON's numeric and string tolerance.
use ken_text::PythonText;
use regex::Regex;
use serde_json::value::RawValue;
use std::sync::OnceLock;
#[derive(Clone, Debug)]
pub(super) enum ConfigValue {
    Object(Vec<(Option<String>, ConfigValue)>),
    Array(Vec<ConfigValue>),
    Text(ConfigText),
    Other { truth: bool, spelling: String },
    Null,
}
/// Config paths retain non-scalar code points until lexical normalization.
#[derive(Clone, Debug)]
pub(super) struct ConfigText {
    scalar: Option<String>,
    pub points: PythonText,
}
impl ConfigText {
    fn parse(raw: &str) -> Option<Self> {
        let scalar: Option<String> = serde_json::from_str(raw).ok();
        let points = if let Some(value) = &scalar {
            PythonText::from(value.as_str())
        } else {
            let text: PythonText = serde_json::from_str(raw).ok()?;
            // Python's JSON decoder combines adjacent escaped surrogate pairs,
            // while PythonText's generic codec preserves individual code points.
            let mut points = Vec::new();
            let mut source = text.codepoints().iter().copied().peekable();
            while let Some(high) = source.next() {
                if (0xd800..=0xdbff).contains(&high)
                    && let Some(&low) = source.peek()
                    && (0xdc00..=0xdfff).contains(&low)
                {
                    source.next();
                    points.push(0x10000 + ((high - 0xd800) << 10) + low - 0xdc00);
                } else {
                    points.push(high);
                }
            }
            PythonText::from_codepoints(points)?
        };
        Some(Self { scalar, points })
    }
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
            value.scalar.as_deref()
        } else {
            None
        }
    }
    pub fn path_text(&self) -> Option<&PythonText> {
        if let Self::Text(value) = self {
            Some(&value.points)
        } else {
            None
        }
    }
    pub fn truth(&self) -> bool {
        match self {
            Self::Object(v) => !v.is_empty(),
            Self::Array(v) => !v.is_empty(),
            Self::Text(v) => !v.points.is_empty(),
            Self::Other { truth, .. } => *truth,
            Self::Null => false,
        }
    }
    pub fn is_null(&self) -> bool {
        matches!(self, Self::Null)
    }
    pub fn python_string(&self) -> Option<String> {
        match self {
            Self::Text(value) => value.scalar.clone(),
            Self::Null => Some("None".into()),
            Self::Other { spelling, .. } => Some(spelling.clone()),
            Self::Array(values) => Some(format!(
                "[{}]",
                values
                    .iter()
                    .map(Self::python_repr)
                    .collect::<Option<Vec<_>>>()?
                    .join(", ")
            )),
            Self::Object(values) => Some(format!(
                "{{{}}}",
                values
                    .iter()
                    .map(|(key, value)| Some(format!(
                        "{}: {}",
                        quote(key.as_deref()?),
                        value.python_repr()?
                    )))
                    .collect::<Option<Vec<_>>>()?
                    .join(", ")
            )),
        }
    }
    fn python_repr(&self) -> Option<String> {
        if let Self::Text(value) = self {
            Some(quote(value.scalar.as_deref()?))
        } else {
            self.python_string()
        }
    }
}
fn quote(value: &str) -> String {
    let delimiter = if value.contains('\'') && !value.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut result = delimiter.to_string();
    for c in value.chars() {
        match c {
            '\\' => result.push_str("\\\\"),
            '\n' => result.push_str("\\n"),
            '\r' => result.push_str("\\r"),
            '\t' => result.push_str("\\t"),
            _ if c == delimiter => {
                result.push('\\');
                result.push(c);
            }
            _ if c.is_control() && (c as u32) <= 0xff => {
                result.push_str(&format!("\\x{:02x}", c as u32))
            }
            _ => result.push(c),
        }
    }
    result.push(delimiter);
    result
}
pub(super) fn jsonc(bytes: &[u8]) -> Option<ConfigValue> {
    let text = String::from_utf8_lossy(bytes)
        .replace("\r\n", "\n")
        .replace('\r', "\n");
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
    fn string(&mut self) -> Option<ConfigText> {
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
                return ConfigText::parse(raw);
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
                    let key = self.string()?.scalar;
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
            "true" => Some(ConfigValue::Other {
                truth: true,
                spelling: "True".into(),
            }),
            "false" => Some(ConfigValue::Other {
                truth: false,
                spelling: "False".into(),
            }),
            "NaN" => Some(ConfigValue::Other {
                truth: true,
                spelling: "nan".into(),
            }),
            "Infinity" => Some(ConfigValue::Other {
                truth: true,
                spelling: "inf".into(),
            }),
            "-Infinity" => Some(ConfigValue::Other {
                truth: true,
                spelling: "-inf".into(),
            }),
            _ => {
                serde_json::from_str::<Box<RawValue>>(raw).ok()?;
                let number: f64 = raw.parse().ok()?;
                Some(ConfigValue::Other {
                    truth: number != 0.0,
                    spelling: if raw.contains(['.', 'e', 'E']) {
                        float_spelling(number)
                    } else if number == 0.0 {
                        "0".into()
                    } else {
                        raw.into()
                    },
                })
            }
        }
    }
}
fn float_spelling(number: f64) -> String {
    let text = format!("{number:?}");
    if let Some((base, exponent)) = text.split_once('e') {
        let value: i32 = exponent.parse().expect("native float exponent");
        format!(
            "{base}e{}{number:02}",
            if value < 0 { '-' } else { '+' },
            number = value.unsigned_abs()
        )
    } else {
        text
    }
}
