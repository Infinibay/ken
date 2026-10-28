//! Python docstring literals and full original escape interpretation.
use crate::PythonText;
use crate::python_unicode::named_character;

pub fn decode(raw: &str) -> Option<PythonText> {
    if raw.contains('\0') {
        return None;
    }
    let quote = raw.find(['\'', '"'])?;
    let prefix = raw[..quote].to_ascii_lowercase();
    if !matches!(prefix.as_str(), "" | "r" | "u") {
        return None;
    }
    let quoted = &raw[quote..];
    let delimiter = if quoted.starts_with("\"\"\"") {
        "\"\"\""
    } else if quoted.starts_with("'''") {
        "'''"
    } else {
        &quoted[..1]
    };
    if quoted.len() < 2 * delimiter.len() || !quoted.ends_with(delimiter) {
        return None;
    }
    let body = &quoted[delimiter.len()..quoted.len() - delimiter.len()];
    let body = body.replace("\r\n", "\n").replace('\r', "\n");
    if prefix == "r" {
        return Some(body.into());
    }
    // py_literal's short-string parser is reliable; normalize the delimiter and
    // literal line breaks before invoking it. Preserve original escape pairs.
    let mut encoded = String::from("\"");
    let mut points = Vec::new();
    let mut chars = body.chars().peekable();
    while let Some(character) = chars.next() {
        match character {
            '\\' => {
                let next = chars.next()?;
                if next == '\n' {
                    continue;
                }
                if matches!(next, 'u' | 'U') {
                    let count = if next == 'u' { 4 } else { 8 };
                    let digits: String = chars.by_ref().take(count).collect();
                    if digits.len() != count || !digits.bytes().all(|b| b.is_ascii_hexdigit()) {
                        return None;
                    }
                    let point = u32::from_str_radix(&digits, 16).ok()?;
                    if (0xd800..=0xdfff).contains(&point) {
                        flush(&mut encoded, &mut points)?;
                        points.push(point);
                    } else {
                        encoded.push_str(&format!("\\U{point:08x}"));
                    }
                } else if next == 'N' {
                    if chars.next() != Some('{') {
                        return None;
                    }
                    let mut name = String::new();
                    let mut closed = false;
                    for ch in chars.by_ref() {
                        if ch == '}' {
                            closed = true;
                            break;
                        }
                        name.push(ch);
                    }
                    if !closed {
                        return None;
                    }
                    let character = named_character(&name)?;
                    encoded.push_str(&format!("\\U{:08x}", character as u32));
                } else {
                    encoded.push('\\');
                    encoded.push(next);
                }
            }
            '"' => encoded.push_str("\\\""),
            '\n' => encoded.push_str("\\n"),
            _ => encoded.push(character),
        }
    }
    flush(&mut encoded, &mut points)?;
    PythonText::from_codepoints(points)
}
fn flush(encoded: &mut String, points: &mut Vec<u32>) -> Option<()> {
    encoded.push('"');
    let py_literal::Value::String(value) = encoded.parse().ok()? else {
        return None;
    };
    points.extend(value.chars().map(u32::from));
    encoded.clear();
    encoded.push('"');
    Some(())
}
