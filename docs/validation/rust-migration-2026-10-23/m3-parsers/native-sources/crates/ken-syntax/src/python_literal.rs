//! Python docstring literals and full original escape interpretation.
use crate::python_unicode::named_character;

pub(crate) fn decode(raw: &str) -> Option<String> {
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
        return Some(body);
    }
    // py_literal's short-string parser is reliable; normalize the delimiter and
    // literal line breaks before invoking it. Preserve original escape pairs.
    let mut encoded = String::from("\"");
    let mut chars = body.chars().peekable();
    while let Some(character) = chars.next() {
        match character {
            '\\' => {
                let next = chars.next()?;
                if next == '\n' {
                    continue;
                }
                if next == 'N' {
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
    encoded.push('"');
    match encoded.parse::<py_literal::Value>().ok()? {
        py_literal::Value::String(value) => Some(value),
        _ => None,
    }
}
