//! Annotation syntax descriptors preserve spelling without claiming nominal identity.
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::sync::OnceLock;
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct TypeRef {
    pub kind: String,
    pub native: String,
    #[serde(default)]
    pub arguments: Vec<TypeRef>,
    #[serde(default)]
    pub bits: Option<u16>,
    #[serde(default)]
    pub signed: Option<bool>,
    #[serde(default)]
    pub extent: Option<String>,
    #[serde(default)]
    pub rank: Option<usize>,
    #[serde(default)]
    pub qualifiers: Vec<String>,
}
impl TypeRef {
    pub(crate) fn new(kind: &str, native: &str) -> Self {
        Self {
            kind: kind.into(),
            native: native.into(),
            arguments: vec![],
            bits: None,
            signed: None,
            extent: None,
            rank: None,
            qualifiers: vec![],
        }
    }
    fn nested(kind: &str, native: &str, arguments: Vec<Self>) -> Self {
        Self {
            arguments,
            ..Self::new(kind, native)
        }
    }
}
pub(crate) fn whitespace(c: char) -> bool {
    c.is_whitespace() || matches!(c, '\x1c'..='\x1f')
}
pub(crate) fn trim(s: &str) -> &str {
    s.trim_matches(whitespace)
}
pub fn split_types(text: &str, separator: char) -> Vec<String> {
    let mut depth = 0i64;
    let mut start = 0;
    let mut parts = Vec::new();
    for (i, c) in text.char_indices() {
        if matches!(c, '<' | '[' | '(') {
            depth += 1;
        } else if matches!(c, '>' | ']' | ')') {
            depth -= 1;
        } else if c == separator && depth == 0 {
            parts.push(trim(&text[start..i]).into());
            start = i + c.len_utf8();
        }
    }
    parts.push(trim(&text[start..]).into());
    parts
}
fn character(c: char, decimal: bool) -> bool {
    if decimal {
        ken_text::unicode::decimal(c)
    } else {
        ken_text::unicode::word(c)
    }
}
fn nominal(s: &str) -> bool {
    !s.is_empty()
        && s.chars()
            .all(|c| matches!(c, '.' | ':') || character(c, false))
}
struct Patterns {
    parenthesized: Regex,
    suffix_space: Regex,
    suffix_pointer: Regex,
    prefix: Regex,
}
fn patterns() -> &'static Patterns {
    static PATTERNS: OnceLock<Patterns> = OnceLock::new();
    PATTERNS.get_or_init(|| Patterns {
        parenthesized: Regex::new(r"\([^)]*[*&]").unwrap(),
        suffix_space: Regex::new(r"^(.+?)[\s\x1c-\x1f]+((?:(?:const|volatile)[\s\x1c-\x1f]*)+)\z")
            .unwrap(),
        suffix_pointer: Regex::new(r"^(.*?[*&])((?:(?:const|volatile)[\s\x1c-\x1f]*)+)\z").unwrap(),
        prefix: Regex::new(r"^((?:(?:const|volatile)[\s\x1c-\x1f]+)+)(.+)\z").unwrap(),
    })
}
pub fn parse_type(annotation: &str, language: &str) -> TypeRef {
    parse(annotation, language, 0)
}
fn parse(annotation: &str, language: &str, depth: usize) -> TypeRef {
    let text = trim(
        trim(annotation)
            .strip_prefix(':')
            .unwrap_or(trim(annotation)),
    );
    if text.is_empty() || text == "unknown" {
        return TypeRef::new("unknown", text);
    }
    if depth > 32 || text.chars().count() > 10000 {
        return TypeRef::new("opaque", text);
    }
    let child = |s: &str| parse(s, language, depth + 1);
    let nested = |kind: &str, s: &str| TypeRef::nested(kind, text, vec![child(s)]);
    let union = split_types(text, '|');
    if union.len() > 1 {
        return TypeRef::nested("union", text, union.iter().map(|v| child(v)).collect());
    }
    if matches!(language, "csharp" | "typescript")
        && let Some(inner) = text.strip_suffix('?')
    {
        return nested("optional", inner);
    }
    if language == "rust"
        && let Some(inner) = text.strip_prefix('&')
    {
        let mut inner = inner.trim_start_matches(whitespace);
        if let Some(lifetime) = inner.strip_prefix('\'')
            && lifetime
                .chars()
                .next()
                .is_some_and(|c| c.is_ascii_alphabetic() || c == '_')
        {
            let end = lifetime
                .char_indices()
                .take_while(|(_, c)| character(*c, false))
                .map(|(i, c)| i + c.len_utf8())
                .last()
                .unwrap();
            inner = lifetime[end..].trim_start_matches(whitespace);
        }
        if let Some(rest) = inner.strip_prefix("mut")
            && rest.chars().next().is_some_and(whitespace)
        {
            inner = rest.trim_start_matches(whitespace);
        }
        return nested("reference", inner);
    }
    if matches!(language, "cpp" | "go")
        && let Some(inner) = text.strip_prefix('*')
    {
        return nested("pointer", inner);
    }
    if language == "cpp" {
        let p = patterns();
        if !text.ends_with('>') && p.parenthesized.is_match(text) {
            return TypeRef::new("opaque", text);
        }
        let suffix = [
            p.suffix_space.captures(text),
            p.suffix_pointer.captures(text),
        ]
        .into_iter()
        .flatten()
        .min_by_key(|m| m[1].chars().count());
        if let Some(parts) = suffix {
            let mut result = nested("qualified", &parts[1]);
            result.qualifiers = parts[2]
                .split(whitespace)
                .filter(|v| !v.is_empty())
                .map(str::to_owned)
                .collect();
            return result;
        }
        if let Some(inner) = text.strip_suffix("&&") {
            return nested("rvalue_reference", inner);
        }
        if let Some(inner) = text.strip_suffix('*') {
            return nested("pointer", inner);
        }
        if let Some(inner) = text.strip_suffix('&') {
            return nested("reference", inner);
        }
    }
    if language == "go" {
        if let Some(rest) = text.strip_prefix("map[") {
            let mut nesting = 1i64;
            for (i, c) in rest.char_indices() {
                nesting += i64::from(c == '[') - i64::from(c == ']');
                if nesting == 0 {
                    return TypeRef::nested(
                        "map",
                        text,
                        vec![child(&rest[..i]), child(&rest[i + 1..])],
                    );
                }
            }
        }
        if let Some(rest) = text.strip_prefix('[')
            && let Some((extent, element)) = rest.split_once(']')
            && !element.is_empty()
            && !element.contains('\n')
        {
            let mut result = nested(if extent.is_empty() { "slice" } else { "array" }, element);
            result.extent = (!extent.is_empty()).then(|| extent.into());
            return result;
        }
    }
    if language == "rust"
        && let Some(inner) = text.strip_prefix('[').and_then(|s| s.strip_suffix(']'))
    {
        let parts = split_types(inner, ';');
        if matches!(parts.len(), 1 | 2) {
            let mut result = nested(if parts.len() == 2 { "array" } else { "slice" }, &parts[0]);
            result.extent = parts.get(1).cloned();
            return result;
        }
    }
    if language == "cpp"
        && let Some(parts) = patterns().prefix.captures(text)
    {
        let mut result = nested("qualified", &parts[2]);
        result.qualifiers = parts[1]
            .split(whitespace)
            .filter(|v| !v.is_empty())
            .map(str::to_owned)
            .collect();
        return result;
    }
    if matches!(
        language,
        "javascript" | "typescript" | "java" | "csharp" | "cpp"
    ) && let Some((base, extent)) = text.strip_suffix(']').and_then(|s| s.rsplit_once('['))
        && !base.is_empty()
        && !base.contains('\n')
        && extent
            .chars()
            .all(|c| c == ',' || whitespace(c) || character(c, true))
    {
        let mut result = nested("array", base);
        if language == "csharp" {
            result.rank = Some(extent.chars().filter(|c| *c == ',').count() + 1);
        } else {
            result.extent = (!trim(extent).is_empty()).then(|| trim(extent).into());
        }
        return result;
    }
    if let Some((position, _)) = text.char_indices().find(|(_, c)| matches!(c, '<' | '[')) {
        let name = text[..position].trim_end_matches(whitespace);
        let tail = &text[position + 1..];
        if nominal(name) && tail.len() > 1 && tail.ends_with(['>', ']']) && !tail.contains('\n') {
            let base = name
                .rsplit("::")
                .next()
                .unwrap()
                .rsplit('.')
                .next()
                .unwrap();
            let kind = match base {
                "list" | "List" | "Vec" | "vector" => "list",
                "Array" | "array" => "array",
                "dict" | "Dict" | "Map" | "HashMap" | "Dictionary" | "map" | "unordered_map" => {
                    "map"
                }
                "set" | "Set" | "HashSet" => "set",
                "tuple" | "Tuple" => "tuple",
                "Optional" | "Option" => "optional",
                "Union" => "union",
                _ => "generic",
            };
            let mut arguments: Vec<_> = split_types(&tail[..tail.len() - 1], ',')
                .iter()
                .map(|v| child(v))
                .collect();
            if language == "cpp" && base == "array" && arguments.len() == 2 {
                let extent = arguments.pop().unwrap().native;
                let mut result = TypeRef::nested("array", text, arguments);
                result.extent = Some(extent);
                return result;
            }
            return TypeRef::nested(kind, text, arguments);
        }
    }
    if let Some(inner) = text.strip_prefix('(').and_then(|s| s.strip_suffix(')'))
        && text.contains(',')
    {
        return TypeRef::nested(
            "tuple",
            text,
            split_types(inner, ',')
                .iter()
                .filter(|v| !v.is_empty())
                .map(|v| child(v))
                .collect(),
        );
    }
    if language == "python" && matches!(text, "list" | "dict" | "set" | "tuple") {
        return TypeRef::new(if text == "dict" { "map" } else { text }, text);
    }
    if let Some(result) = primitive(text, language) {
        return result;
    }
    TypeRef::new(if nominal(text) { "nominal" } else { "opaque" }, text)
}
fn primitive(text: &str, language: &str) -> Option<TypeRef> {
    let kind = match text {
        "any" | "Any" | "dynamic" => "any",
        "never" | "Never" | "NoReturn" => "never",
        "None" | "NoneType" | "null" | "nil" => "null",
        "void" => "void",
        "bool" | "boolean" | "Boolean" => "bool",
        "str" | "string" | "String" | "std::string" => "str",
        "char" | "wchar_t" | "char16_t" | "char32_t" => "char",
        "number" => "number",
        _ => "",
    };
    if !kind.is_empty() {
        let mut result = TypeRef::new(kind, text);
        if kind == "char" {
            result.bits =
                if text == "char" && matches!(language, "java" | "csharp") || text == "char16_t" {
                    Some(16)
                } else if text == "char32_t" || text == "char" && language == "rust" {
                    Some(32)
                } else {
                    None
                };
        }
        return Some(result);
    }
    let bits = text
        .strip_prefix(['i', 'u'])
        .filter(|s| matches!(*s, "8" | "16" | "32" | "64" | "128"))
        .or_else(|| {
            text.strip_prefix('u')
                .unwrap_or(text)
                .strip_prefix("int")
                .map(|s| s.strip_suffix("_t").unwrap_or(s))
                .filter(|s| matches!(*s, "8" | "16" | "32" | "64"))
        });
    if let Some(bits) = bits {
        let mut result = TypeRef::new("int", text);
        result.bits = Some(bits.parse().unwrap());
        result.signed = Some(!text.starts_with('u'));
        return Some(result);
    }
    if matches!(
        text,
        "int"
            | "Int"
            | "long"
            | "short"
            | "byte"
            | "sbyte"
            | "uint"
            | "ulong"
            | "ushort"
            | "usize"
            | "isize"
            | "rune"
    ) {
        let mut result = TypeRef::new("int", text);
        result.bits = if matches!(language, "java" | "csharp") {
            match text {
                "int" | "uint" => Some(32),
                "long" | "ulong" => Some(64),
                "short" | "ushort" => Some(16),
                "byte" | "sbyte" => Some(8),
                _ => None,
            }
        } else if text == "rune" {
            Some(32)
        } else if text == "byte" && language == "go" {
            Some(8)
        } else {
            None
        };
        result.signed = (language != "python").then(|| {
            !(text.starts_with('u') || text == "byte" && matches!(language, "csharp" | "go"))
        });
        return Some(result);
    }
    if matches!(
        text,
        "float" | "double" | "f32" | "f64" | "float32" | "float64"
    ) {
        let mut result = TypeRef::new("float", text);
        result.bits = if matches!(text, "f32" | "float32")
            || text == "float" && matches!(language, "java" | "csharp")
        {
            Some(32)
        } else if matches!(text, "f64" | "float64")
            || text == "double" && matches!(language, "java" | "csharp")
        {
            Some(64)
        } else {
            None
        };
        return Some(result);
    }
    None
}
