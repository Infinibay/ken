use ken_text::PythonText;
pub fn scalar(value: &PythonText) -> String {
    value
        .codepoints()
        .iter()
        .map(|&p| char::from_u32(p).unwrap_or('\u{fffd}'))
        .collect()
}
pub fn slice(value: &PythonText, start: usize, end: usize) -> PythonText {
    PythonText::from_codepoints(
        value.codepoints()[start.min(value.codepoints().len())
            ..end
                .min(value.codepoints().len())
                .max(start.min(value.codepoints().len()))]
            .to_vec(),
    )
    .expect("existing code points")
}
pub fn prefix(value: &PythonText, count: usize) -> PythonText {
    slice(value, 0, count)
}
pub fn prepend(prefix: &str, value: &PythonText) -> PythonText {
    PythonText::from_codepoints(
        prefix
            .chars()
            .map(u32::from)
            .chain(value.codepoints().iter().copied())
            .collect(),
    )
    .expect("existing code points")
}
fn word(point: u32) -> bool {
    char::from_u32(point).is_some_and(ken_text::unicode::word)
}
pub fn clauses(value: &PythonText) -> Vec<PythonText> {
    let p = value.codepoints();
    let mut start = 0;
    let mut at = 0;
    let mut out = Vec::new();
    while at < p.len() {
        let split = if matches!(p[at], 46 | 59 | 10) {
            1
        } else {
            ["but", "sino"]
                .into_iter()
                .find_map(|w| {
                    let n = w.len();
                    (p[at..].iter().copied().take(n).eq(w.chars().map(u32::from))
                        && (at == 0 || !word(p[at - 1]))
                        && (at + n == p.len() || p.get(at + n).is_some_and(|c| !word(*c))))
                    .then_some(n)
                })
                .unwrap_or(0)
        };
        if split > 0 {
            out.push(slice(value, start, at));
            at += split;
            start = at;
        } else {
            at += 1;
        }
    }
    out.push(slice(value, start, p.len()));
    out
}
pub fn denial_tail(value: &PythonText) -> Option<PythonText> {
    let p = value.codepoints();
    let fold = |c: u32| {
        char::from_u32(c)
            .map(ken_text::unicode::query_literal_fold)
            .map(|c| c.to_ascii_lowercase() as u32)
            .unwrap_or(c)
    };
    for start in 0..p.len() {
        if start > 0 && word(p[start - 1]) {
            continue;
        }
        for phrase in [
            "does not", "do not", "never", "cannot", "must not", "no", "nunca",
        ] {
            let n = phrase.len();
            if start + n <= p.len()
                && p[start..start + n]
                    .iter()
                    .copied()
                    .map(fold)
                    .eq(phrase.chars().map(u32::from))
                && (start + n == p.len() || !word(p[start + n]))
            {
                return Some(slice(value, start + n, p.len()));
            }
        }
    }
    None
}
pub fn fragments(value: &PythonText) -> Vec<PythonText> {
    let p = value.codepoints();
    let mut start = 0;
    let mut at = 0;
    let mut out = Vec::new();
    while at < p.len() {
        let newline = p[at] == 10;
        let whitespace = char::from_u32(p[at]).is_some_and(ken_text::unicode::whitespace);
        let sentence = at > 0 && matches!(p[at - 1], 46 | 33 | 63) && whitespace;
        if newline || sentence {
            let item = slice(value, start, at).trimmed();
            if !item.is_empty() {
                out.push(item);
            }
            at += 1;
            while at < p.len()
                && (p[at] == 10
                    || sentence && char::from_u32(p[at]).is_some_and(ken_text::unicode::whitespace))
            {
                at += 1;
            }
            start = at;
        } else {
            at += 1;
        }
    }
    let item = slice(value, start, p.len()).trimmed();
    if !item.is_empty() {
        out.push(item);
    }
    out
}
