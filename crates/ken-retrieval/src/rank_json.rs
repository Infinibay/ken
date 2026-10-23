//! Compact Python model identity; separate from the spaced M2 asset format.
use super::numeric_ranker::{NumericError, NumericResult};
use ken_text::{PythonText, unicode};
use serde_json::value::RawValue;

pub(crate) fn text(raw: &RawValue) -> NumericResult<PythonText> {
    let points: PythonText =
        serde_json::from_str(raw.get()).map_err(|e| NumericError::value(e.to_string()))?;
    // json.loads joins valid escaped UTF-16 pairs at the JSON boundary.
    let mut joined = Vec::new();
    let mut it = points.codepoints().iter().copied().peekable();
    while let Some(c) = it.next() {
        if (0xd800..=0xdbff).contains(&c)
            && it.peek().is_some_and(|d| (0xdc00..=0xdfff).contains(d))
        {
            let d = it.next().unwrap();
            joined.push(0x10000 + ((c - 0xd800) << 10) + (d - 0xdc00));
        } else {
            joined.push(c)
        }
    }
    Ok(PythonText::from_codepoints(joined).expect("existing JSON points"))
}
pub(crate) fn quote(text: &PythonText) -> String {
    let mut out = String::from("\"");
    for &c in text.codepoints() {
        match c {
            0x22 => out.push_str("\\\""),
            0x5c => out.push_str("\\\\"),
            8 => out.push_str("\\b"),
            12 => out.push_str("\\f"),
            10 => out.push_str("\\n"),
            13 => out.push_str("\\r"),
            9 => out.push_str("\\t"),
            0..=31 | 0xd800..=0xdfff => out.push_str(&format!("\\u{c:04x}")),
            _ => out.push(char::from_u32(c).expect("Python scalar")),
        }
    }
    out.push('"');
    out
}
pub(crate) fn float(value: f64) -> String {
    // Both runtimes use shortest round-trip digits; Python chooses fixed form
    // at decimal exponents -4..15 and always writes a decimal point for integers.
    let raw = format!("{:?}", value.abs());
    let (mantissa, exponent) = raw
        .split_once('e')
        .map_or((raw.as_str(), 0), |(a, b)| (a, b.parse::<i32>().unwrap()));
    let decimal = mantissa.find('.').unwrap_or(mantissa.len()) as i32;
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    let significant = digits.trim_start_matches('0');
    if significant.is_empty() {
        return if value.is_sign_negative() {
            "-0.0"
        } else {
            "0.0"
        }
        .into();
    }
    let first = (digits.len() - significant.len()) as i32;
    let exp = decimal + exponent - first - 1;
    let digits = significant.trim_end_matches('0');
    let mut out = if value.is_sign_negative() {
        "-".into()
    } else {
        String::new()
    };
    if !(-4..16).contains(&exp) {
        out.push_str(&digits[..1]);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        out.push('e');
        out.push(if exp < 0 { '-' } else { '+' });
        out.push_str(&format!("{:02}", exp.abs()));
    } else {
        let point = exp + 1;
        if point <= 0 {
            out.push_str("0.");
            out.push_str(&"0".repeat((-point) as usize));
            out.push_str(digits);
        } else if point as usize >= digits.len() {
            out.push_str(digits);
            out.push_str(&"0".repeat(point as usize - digits.len()));
            out.push_str(".0");
        } else {
            out.push_str(&digits[..point as usize]);
            out.push('.');
            out.push_str(&digits[point as usize..]);
        }
    }
    out
}
pub(crate) fn kind(raw: &RawValue) -> &'static str {
    match raw.get().as_bytes()[0] {
        b'n' => "NoneType",
        b't' | b'f' => "bool",
        b'"' => "str",
        b'[' => "list",
        b'{' => "dict",
        _ => {
            if raw.get().contains(['.', 'e', 'E']) {
                "float"
            } else {
                "int"
            }
        }
    }
}
pub(crate) fn number(raw: &RawValue) -> NumericResult<f64> {
    match kind(raw) {
        "bool" => Ok(if raw.get() == "true" { 1. } else { 0. }),
        "int" | "float" => raw
            .get()
            .parse()
            .map_err(|_| NumericError::value("invalid ranking number")),
        "str" => {
            let original = text(raw)?;
            let normalized: String = original
                .codepoints()
                .iter()
                .map(|&p| char::from_u32(p).unwrap_or('\u{ffff}'))
                .map(|c| {
                    unicode::decimal_digit(c)
                        .and_then(|d| char::from_digit(d, 10))
                        .unwrap_or(c)
                })
                .collect();
            let s = normalized.trim_matches(|c: char| {
                c.is_ascii_whitespace() || (!c.is_ascii() && unicode::whitespace(c))
            });
            let chars: Vec<_> = s.chars().collect();
            let underscores = chars.iter().enumerate().all(|(i, c)| {
                *c != '_'
                    || (i > 0
                        && i + 1 < chars.len()
                        && chars[i - 1].is_ascii_digit()
                        && chars[i + 1].is_ascii_digit())
            });
            let stripped = s.replace('_', "");
            if underscores && !stripped.is_empty() {
                let unsigned = stripped.strip_prefix(['+', '-']).unwrap_or(&stripped);
                let special = unsigned.eq_ignore_ascii_case("inf")
                    || unsigned.eq_ignore_ascii_case("infinity")
                    || unsigned.eq_ignore_ascii_case("nan");
                let numeric = unsigned
                    .chars()
                    .all(|c| c.is_ascii_digit() || matches!(c, '.' | 'e' | 'E' | '+' | '-'));
                if (special || numeric)
                    && let Ok(value) = stripped.parse::<f64>()
                {
                    return Ok(value);
                }
            }
            Err(NumericError::value(format!(
                "could not convert string to float: {}",
                repr(&original)
            )))
        }
        name => Err(NumericError::typed(
            "TypeError",
            format!("float() argument must be a string or a real number, not '{name}'"),
        )),
    }
}
fn repr(text: &PythonText) -> String {
    let q = if text.codepoints().contains(&39) && !text.codepoints().contains(&34) {
        '"'
    } else {
        '\''
    };
    let mut out = q.to_string();
    for &p in text.codepoints() {
        match p {
            10 => out.push_str("\\n"),
            13 => out.push_str("\\r"),
            9 => out.push_str("\\t"),
            92 => out.push_str("\\\\"),
            p if p == q as u32 => {
                out.push('\\');
                out.push(q)
            }
            0..=31 | 127 => out.push_str(&format!("\\x{p:02x}")),
            0xd800..=0xdfff => out.push_str(&format!("\\u{p:04x}")),
            _ => out.push(char::from_u32(p).unwrap()),
        }
    }
    out.push(q);
    out
}

/// Retain JSON object insertion order, lossless keys, and last duplicate values.
pub(crate) struct Object(Vec<(PythonText, Box<RawValue>)>);
impl Object {
    pub(crate) fn len(&self) -> usize {
        self.0.len()
    }
    pub(crate) fn get(&self, key: &str) -> Option<&RawValue> {
        let key = PythonText::from(key);
        self.0.iter().find(|(k, _)| *k == key).map(|(_, v)| &**v)
    }
    pub(crate) fn contains_key(&self, key: &str) -> bool {
        self.get(key).is_some()
    }
    pub(crate) fn keys(&self) -> impl Iterator<Item = &PythonText> {
        self.0.iter().map(|(k, _)| k)
    }
}
pub(crate) fn object(raw: &str) -> NumericResult<Object> {
    let checked: Box<RawValue> =
        serde_json::from_str(raw).map_err(|e| NumericError::value(e.to_string()))?;
    let raw = checked.get();
    if !raw.starts_with('{') {
        return Err(NumericError::value("JSON object required"));
    }
    let mut remaining = raw[1..].trim_start();
    let mut entries: Vec<(PythonText, Box<RawValue>)> = Vec::new();
    while !remaining.starts_with('}') {
        let mut escaped = false;
        let mut end = 1;
        for (i, b) in remaining.bytes().enumerate().skip(1) {
            if escaped {
                escaped = false;
            } else if b == b'\\' {
                escaped = true;
            } else if b == b'"' {
                end = i + 1;
                break;
            }
        }
        let key = RawValue::from_string(remaining[..end].into())
            .map_err(|e| NumericError::value(e.to_string()))?;
        let key = text(&key)?;
        remaining = remaining[end..]
            .trim_start()
            .strip_prefix(':')
            .expect("validated object colon")
            .trim_start();
        let mut stream = serde_json::Deserializer::from_str(remaining).into_iter::<Box<RawValue>>();
        let value = stream
            .next()
            .expect("validated value")
            .map_err(|e| NumericError::value(e.to_string()))?;
        remaining = remaining[stream.byte_offset()..].trim_start();
        if let Some((_, old)) = entries.iter_mut().find(|(k, _)| *k == key) {
            *old = value;
        } else {
            entries.push((key, value));
        }
        if let Some(rest) = remaining.strip_prefix(',') {
            remaining = rest.trim_start();
        }
    }
    Ok(Object(entries))
}
