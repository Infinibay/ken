//! Lossless interpretation of Python source strings used by compatibility syntax.
pub(crate) fn decode(text: &str) -> Option<ken_text::PythonText> {
    let mut rest = text.trim();
    let mut points = vec![];
    let mut any = false;
    while !rest.is_empty() {
        let quote = rest.find(['\'', '"'])?;
        let prefix = rest[..quote].to_ascii_lowercase();
        if !matches!(prefix.as_str(), "" | "r" | "u") {
            return None;
        }
        let quoted = &rest[quote..];
        let delimiter = if quoted.starts_with("\"\"\"") || quoted.starts_with("\'\'\'") {
            3
        } else {
            1
        };
        let token = &quoted[..delimiter];
        let body = &quoted[delimiter..];
        let mut end = None;
        let mut chars = body.char_indices();
        while let Some((i, c)) = chars.next() {
            if c == '\\' {
                chars.next();
                continue;
            }
            if body[i..].starts_with(token) {
                end = Some(i);
                break;
            }
            if delimiter == 1 && matches!(c, '\n' | '\r') {
                return None;
            }
        }
        let end = end?;
        let body = body[..end].replace("\r\n", "\n").replace('\r', "\n");
        if prefix == "r" {
            points.extend(body.chars().map(u32::from));
        } else {
            let mut encoded = String::from("\"");
            let mut chars = body.chars().peekable();
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
            while let Some(c) = chars.next() {
                match c {
                    '\\' => {
                        let next = chars.next()?;
                        if next == '\n' {
                            continue;
                        }
                        if matches!(next, 'u' | 'U') {
                            let count = if next == 'u' { 4 } else { 8 };
                            let digits = chars.by_ref().take(count).collect::<String>();
                            if digits.len() != count
                                || !digits.bytes().all(|c| c.is_ascii_hexdigit())
                            {
                                return None;
                            }
                            let point = u32::from_str_radix(&digits, 16).ok()?;
                            if point > 0x10ffff {
                                return None;
                            }
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
                            for c in chars.by_ref() {
                                if c == '}' {
                                    closed = true;
                                    break;
                                }
                                name.push(c);
                            }
                            if !closed {
                                return None;
                            }
                            let point = unicode_names2::character(&name)
                                .filter(|c| crate::lexer::assigned(*c))?;
                            encoded.push_str(&format!("\\U{:08x}", point as u32));
                        } else {
                            encoded.push('\\');
                            encoded.push(next);
                        }
                    }
                    '"' => encoded.push_str("\\\""),
                    '\n' => encoded.push_str("\\n"),
                    _ => encoded.push(c),
                }
            }
            flush(&mut encoded, &mut points)?;
        }
        any = true;
        rest = quoted[delimiter + end + delimiter..].trim_start();
    }
    if any {
        ken_text::PythonText::from_codepoints(points)
    } else {
        None
    }
}
