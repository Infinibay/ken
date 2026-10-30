use ken_text::PythonText as Text;
pub(crate) fn join(items: impl IntoIterator<Item = Text>, separator: &str) -> Text {
    let mut out = Vec::new();
    for (i, item) in items.into_iter().enumerate() {
        if i > 0 {
            out.extend(separator.chars().map(u32::from));
        }
        out.extend_from_slice(item.codepoints());
    }
    Text::from_codepoints(out).expect("valid text parts")
}
pub(crate) fn append(a: &Text, separator: &str, b: impl Into<Text>) -> Text {
    if a.is_empty() {
        b.into()
    } else {
        join([a.clone(), b.into()], separator)
    }
}
/// Matchers treat surrogate codepoints as non-word delimiters; public text keeps
/// the original codepoints throughout ranking traces and serialization.
pub(crate) fn matching(text: &Text) -> String {
    text.codepoints()
        .iter()
        .map(|p| char::from_u32(*p).unwrap_or('\u{fffd}'))
        .collect()
}
pub(crate) fn whitespace(point: u32) -> bool {
    char::from_u32(point).is_some_and(|c| c.is_whitespace() || matches!(c, '\x1c'..='\x1f'))
}
pub(crate) fn compact(text: &Text, limit: usize) -> Text {
    let mut out = Vec::new();
    let mut space = false;
    for &point in text.codepoints() {
        if whitespace(point) {
            space = !out.is_empty();
        } else {
            if space {
                out.push(32);
                space = false;
            }
            out.push(point);
        }
    }
    if out.len() > limit {
        out.truncate(limit.saturating_sub(1));
        while out.last().is_some_and(|p| whitespace(*p)) {
            out.pop();
        }
        out.push(0x2026);
    }
    Text::from_codepoints(out).expect("retained codepoints")
}
pub(crate) fn utf8_ignore(bytes: &[u8]) -> String {
    let mut out = String::new();
    let mut rest = bytes;
    while !rest.is_empty() {
        match std::str::from_utf8(rest) {
            Ok(text) => {
                out.push_str(text);
                break;
            }
            Err(error) => {
                let valid = error.valid_up_to();
                out.push_str(std::str::from_utf8(&rest[..valid]).expect("valid prefix"));
                let Some(skip) = error.error_len() else { break };
                rest = &rest[valid + skip..];
            }
        }
    }
    out
}
pub(crate) fn splitlines(text: &Text) -> Vec<Text> {
    let mut out = Vec::new();
    let points = text.codepoints();
    let (mut start, mut i) = (0, 0);
    while i < points.len() {
        if matches!(
            points[i],
            10 | 13 | 11 | 12 | 28..=30 | 0x85 | 0x2028 | 0x2029
        ) {
            out.push(Text::from_codepoints(points[start..i].to_vec()).unwrap());
            let crlf = points[i] == 13 && points.get(i + 1) == Some(&10);
            i += if crlf { 2 } else { 1 };
            start = i;
        } else {
            i += 1;
        }
    }
    if start < points.len() {
        out.push(Text::from_codepoints(points[start..].to_vec()).unwrap());
    }
    out
}
