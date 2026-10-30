//! One vocabulary for source indexing and query consumers.
use ken_text::unicode::{casefold, decimal, word};
use std::{
    collections::{BTreeSet, HashMap, HashSet},
    sync::{Mutex, OnceLock},
};
use unicode_normalization::UnicodeNormalization;
pub const NAME_TOKEN_VERSION: usize = 1;
pub const TOKENIZER_VERSION: &str = "code-fields-v1";
const STOP: &str = "the and for with from into this that what where when why how fix bug error traceback file line test tests code src function class method module este esta esto ese esa eso con para que por los las una uno momento ahora sigue seguir continua continuar continuemos seguimos path foco extra cual quien donde cuando como clase codigo código fichero archivo funcion función";
const CODE_STOP: &str = "a an the is are it its be been being this that these those where what which how does do did with from for to of in on at and or el la los las un una unos unas de del al en con para por y o que qué donde dónde cómo cual cuál se es son está estan";
fn stop(text: &str, term: &str) -> bool {
    text.split(' ').any(|s| s == term)
}
/// Exact left-to-right match of [A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+.
/// The literal channel shares name stopwords without adding token aliases.
pub fn is_name_stopword(word: &str) -> bool {
    stop(STOP, word)
}

pub fn split_camel(text: &str) -> Vec<String> {
    let chars: Vec<_> = text.chars().collect();
    let mut out = Vec::new();
    let mut i = 0;
    while i < chars.len() {
        let start = i;
        let c = chars[i];
        if c.is_ascii_lowercase()
            || (c.is_ascii_uppercase() && chars.get(i + 1).is_some_and(char::is_ascii_lowercase))
        {
            i += 1;
            while i < chars.len() && chars[i].is_ascii_lowercase() {
                i += 1
            }
            out.push(chars[start..i].iter().collect());
        } else if c.is_ascii_uppercase() {
            let mut end = i + 1;
            while end < chars.len() && chars[end].is_ascii_uppercase() {
                end += 1
            }
            let take = if end == chars.len() { end } else { end - 1 };
            if take > start {
                i = take;
                out.push(chars[start..i].iter().collect());
            } else {
                i += 1
            }
        } else if decimal(c) {
            i += 1;
            while i < chars.len() && decimal(chars[i]) {
                i += 1
            }
            out.push(chars[start..i].iter().collect());
        } else {
            i += 1
        }
    }
    out
}
fn aliases(token: &str) -> &'static [&'static str] {
    match token {
        "class" => &["class"],
        "code" => &["code"],
        "file" => &["file"],
        "scheduler" | "scheduling" => &["sched"],
        "parsear" | "parsea" | "parseo" => &["parse", "parser", "parsers", "parsed"],
        "parse" => &["parser", "parsers", "parsed"],
        "parser" => &["parse", "parsers", "parsed"],
        "parsing" => &["parse", "parser", "parsers", "parsed"],
        "archivo" | "fichero" => &["file", "source"],
        "codigo" | "código" => &["code", "source"],
        "clase" => &["class"],
        _ => &[],
    }
}
pub fn name_tokens(text: &str, extra_stopwords: &BTreeSet<String>) -> BTreeSet<String> {
    let text = text.replace(['-', '.', '/'], "_");
    let b = text.as_bytes();
    let mut i = 0;
    let mut raw = BTreeSet::new();
    while i < b.len() {
        if !b[i].is_ascii_alphabetic() {
            i += 1;
            continue;
        }
        let start = i;
        i += 1;
        while i < b.len() && (b[i].is_ascii_alphanumeric() || b[i] == b'_') {
            i += 1
        }
        if i - start < 3 {
            continue;
        }
        for part in text[start..i].split('_') {
            for piece in split_camel(part) {
                if piece.chars().count() >= 3 {
                    raw.insert(piece.to_lowercase());
                }
            }
        }
    }
    let mut out: BTreeSet<_> = raw
        .iter()
        .filter(|s| !stop(STOP, s) && !extra_stopwords.contains(*s))
        .cloned()
        .collect();
    for t in raw {
        out.extend(aliases(&t).iter().map(|s| String::from(*s)));
    }
    out
}
fn lexemes(text: &str) -> Vec<&str> {
    let chars: Vec<_> = text.char_indices().collect();
    let mut out = Vec::new();
    let mut i = 0;
    while i < chars.len() {
        if chars[i].1 == '_' || !word(chars[i].1) {
            i += 1;
            continue;
        }
        let start = chars[i].0;
        i += 1;
        loop {
            while i < chars.len() && word(chars[i].1) {
                i += 1
            }
            if i + 1 < chars.len()
                && matches!(chars[i].1, '.' | '$' | '/' | '-')
                && chars[i + 1].1 != '_'
                && word(chars[i + 1].1)
            {
                i += 2
            } else {
                break;
            }
        }
        let end = chars.get(i).map_or(text.len(), |p| p.0);
        out.push(&text[start..end]);
    }
    out
}
fn split_identifier(raw: &str) -> Vec<String> {
    let mut variants = BTreeSet::from([casefold(raw)]);
    for part in raw.split(['.', '_', '$', '/', '-']) {
        variants.insert(casefold(part));
        variants.extend(split_camel(part).iter().map(|p| casefold(p)));
    }
    variants
        .into_iter()
        .filter(|s| !s.is_empty() && !stop(CODE_STOP, s))
        .collect()
}
struct Cache {
    values: HashMap<String, (Vec<String>, u64)>,
    order: BTreeSet<(u64, String)>,
    tick: u64,
}
fn identifier(raw: &str) -> Vec<String> {
    if raw.chars().count() > 256 {
        return split_identifier(raw);
    }
    static CACHE: OnceLock<Mutex<Cache>> = OnceLock::new();
    let mut cache = CACHE
        .get_or_init(|| {
            Mutex::new(Cache {
                values: HashMap::new(),
                order: BTreeSet::new(),
                tick: 0,
            })
        })
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    cache.tick += 1;
    let tick = cache.tick;
    if let Some((value, previous)) = cache.values.get(raw).cloned() {
        cache.order.remove(&(previous, raw.into()));
        cache.order.insert((tick, raw.into()));
        cache.values.get_mut(raw).expect("cached key").1 = tick;
        return value;
    }
    let value = split_identifier(raw);
    if cache.values.len() == 16384 {
        let (_, key) = cache.order.pop_first().expect("full cache");
        cache.values.remove(&key);
    }
    cache.order.insert((tick, raw.into()));
    cache.values.insert(raw.into(), (value.clone(), tick));
    value
}
pub fn code_tokens(text: &str) -> Vec<String> {
    lexemes(&text.nfkc().collect::<String>())
        .into_iter()
        .flat_map(identifier)
        .collect()
}
/// Surrogates are non-word normalization barriers, like NUL, in Python's vocabulary.
pub fn code_tokens_python(text: &ken_text::PythonText) -> Vec<String> {
    let scalar: String = text
        .codepoints()
        .iter()
        .map(|&p| char::from_u32(p).unwrap_or('\0'))
        .collect();
    code_tokens(&scalar)
}
pub fn code_terms(text: &str, limit: Option<usize>) -> Vec<String> {
    if limit == Some(0) {
        return vec![];
    }
    let normalized: String = text.nfkc().collect();
    let mut seen_words = HashSet::new();
    let mut seen = HashSet::new();
    let mut out = Vec::new();
    for raw in lexemes(&normalized) {
        if !seen_words.insert(raw) {
            continue;
        }
        for term in identifier(raw) {
            if seen.insert(term.clone()) {
                out.push(term);
                if limit == Some(out.len()) {
                    return out;
                }
            }
        }
    }
    out
}

/// Lossless Python text uses non-word barriers for isolated surrogate code points.
pub fn code_terms_python(text: &ken_text::PythonText, limit: Option<usize>) -> Vec<String> {
    let scalar: String = text
        .codepoints()
        .iter()
        .map(|&p| char::from_u32(p).unwrap_or('\0'))
        .collect();
    code_terms(&scalar, limit)
}
