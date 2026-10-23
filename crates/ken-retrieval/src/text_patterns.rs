//! Frozen text matching with original Python codepoint capture coordinates.
use ken_text::{PythonText, unicode};
use onig::{Regex, RegexOptions, Syntax};
use std::{
    collections::HashMap,
    sync::{Arc, Mutex, OnceLock},
};

pub(crate) fn text(points: &[u32]) -> PythonText {
    PythonText::from_codepoints(points.to_vec()).expect("existing Python points")
}
pub(crate) fn slice(value: &PythonText, start: usize, end: usize) -> PythonText {
    text(&value.codepoints()[start..end])
}
pub(crate) fn tail(value: &PythonText, start: usize) -> PythonText {
    slice(value, start, value.codepoints().len())
}
pub(crate) fn fold(value: &PythonText) -> PythonText {
    let mut points = Vec::new();
    for &point in value.codepoints() {
        match char::from_u32(point) {
            Some(c) => points.extend(unicode::casefold(&c.to_string()).chars().map(u32::from)),
            None => points.push(point),
        }
    }
    text(&points)
}
pub(crate) fn words(value: &PythonText) -> Vec<PythonText> {
    value
        .codepoints()
        .split(|c| char::from_u32(*c).is_some_and(unicode::whitespace))
        .filter(|v| !v.is_empty())
        .map(text)
        .collect()
}
pub(crate) fn strip_chars(
    value: &PythonText,
    chars: &[u32],
    left: bool,
    right: bool,
) -> PythonText {
    let points = value.codepoints();
    let mut start = 0;
    let mut end = points.len();
    if left {
        while start < end && chars.contains(&points[start]) {
            start += 1;
        }
    }
    if right {
        while end > start && chars.contains(&points[end - 1]) {
            end -= 1;
        }
    }
    text(&points[start..end])
}
pub(crate) struct Capture {
    pub start: usize,
    pub end: usize,
    pub whole: PythonText,
    pub groups: Vec<Option<PythonText>>,
    pub named: HashMap<String, PythonText>,
}
struct Compiled {
    regex: Regex,
    names: HashMap<String, usize>,
}
type PatternCache = Mutex<HashMap<(String, bool), Arc<Compiled>>>;
fn compile(pattern: &str, ignore_case: bool) -> Arc<Compiled> {
    static CACHE: OnceLock<PatternCache> = OnceLock::new();
    let mut cache = CACHE
        .get_or_init(Default::default)
        .lock()
        .expect("query pattern cache");
    cache.entry((pattern.into(),ignore_case)).or_insert_with(||{
        let word=unicode::word_class_content();let wc=format!("[{word}]");
        let space="\\x09-\\x0d\\x1c-\\x20\u{85}\u{a0}\u{1680}\u{2000}-\u{200a}\u{2028}\u{2029}\u{202f}\u{205f}\u{3000}";
        let mut out=String::new();let mut chars=pattern.chars();let mut in_class=false;
        while let Some(c)=chars.next() {
            if c=='\\' {
                let next=chars.next().expect("complete frozen escape");
                match next {
                    'w'=>{if in_class {out.push_str(&word)}else{out.push_str(&wc)}},
                    's'=>{if in_class {out.push_str(space)}else{out.push('[');out.push_str(space);out.push(']')}},
                    'b' if !in_class=>out.push_str(&format!("(?:(?<!{wc})(?={wc})|(?<={wc})(?!{wc}))")),
                    _=>{out.push('\\');out.push(next)}
                }
            } else {if c=='[' {in_class=true;}else if c==']'{in_class=false;}out.push(c);}
        }
        let regex=Regex::with_options(&out,RegexOptions::REGEX_OPTION_NONE,Syntax::python()).unwrap_or_else(|e|panic!("frozen query pattern {pattern}: {e}"));
        let mut names=HashMap::new();regex.foreach_name(|name,ids|{names.insert(name.into(),ids[0]as usize);true});
        Arc::new(Compiled{regex,names})
    }).clone()
}
pub(crate) fn captures(pattern: &str, ignore_case: bool, input: &PythonText) -> Vec<Capture> {
    let compiled = compile(pattern, ignore_case);
    let mut scalar = String::new();
    let mut positions = Vec::new();
    for (index, &point) in input.codepoints().iter().enumerate() {
        positions.push((scalar.len(), index));
        let c = char::from_u32(point).unwrap_or('\u{ffff}');
        scalar.push(if ignore_case {
            unicode::query_literal_fold(c)
        } else {
            c
        });
    }
    positions.push((scalar.len(), input.codepoints().len()));
    let locate = |offset| {
        positions[positions
            .binary_search_by_key(&offset, |p| p.0)
            .expect("regex scalar boundary")]
        .1
    };
    compiled
        .regex
        .captures_iter(&scalar)
        .map(|m| {
            let ranges: Vec<_> = (0..m.len())
                .map(|i| m.pos(i).map(|(a, b)| (locate(a), locate(b))))
                .collect();
            let groups: Vec<_> = ranges
                .iter()
                .map(|r| r.map(|(a, b)| slice(input, a, b)))
                .collect();
            let (start, end) = ranges[0].expect("whole match");
            let named = compiled
                .names
                .iter()
                .filter_map(|(name, &i)| groups[i].clone().map(|v| (name.clone(), v)))
                .collect();
            Capture {
                start,
                end,
                whole: groups[0].clone().unwrap(),
                groups,
                named,
            }
        })
        .collect()
}
pub(crate) fn find(pattern: &str, ignore_case: bool, input: &PythonText) -> Option<Capture> {
    captures(pattern, ignore_case, input).into_iter().next()
}
pub(crate) fn has(pattern: &str, ignore_case: bool, input: &PythonText) -> bool {
    find(pattern, ignore_case, input).is_some()
}
pub(crate) fn full(pattern: &str, input: &PythonText) -> Option<Capture> {
    find(pattern, false, input).filter(|m| m.start == 0 && m.end == input.codepoints().len())
}
