//! Interpret explicit source requests; behavioral prose grants no accidental identity.
use crate::{
    query::SearchRequest,
    text_patterns::{self as p},
};
use ken_text::PythonText;
use serde::{Deserialize, Serialize};
const BOUNDARIES: &str = "function method class module file symbol implementation handler helper función funcion método metodo clase módulo modulo archivo implementación that which where who when whose que in of for from with to en de con para por";
const KINDS: &str = "class|struct|interface|enum|trait|type|function|method|utility|helper|clase|tipo|iterador|iterator";
const MODIFIERS: &str = "public|private|protected|abstract|sealed|final|static|async";
const NAME: &str = r"`?[\w$]+(?:[.:]+[\w$]+)*`?";
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct QueryIntent {
    pub purpose: String,
    pub identity: bool,
    pub identifiers: Vec<String>,
    pub kind: Option<String>,
}
fn scalar(value: &PythonText) -> String {
    value.to_utf8().expect("matched scalar query token")
}
fn has_boundary_word(value: &PythonText) -> bool {
    p::words(value).iter().any(|word| {
        word.to_utf8()
            .is_some_and(|s| BOUNDARIES.split_whitespace().any(|b| b == s))
    })
}
fn raw_identifier(query: &PythonText) -> Option<String> {
    let value = query.clone().trimmed();
    let s = value.to_utf8()?;
    let mut chars = s.chars();
    if !chars
        .next()
        .is_some_and(|c| c.is_ascii_alphabetic() || c == '_')
        || !chars.all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '.'))
    {
        return None;
    }
    Some(s)
}
fn named(query: &PythonText) -> Option<(String, Option<String>)> {
    let patterns = [
        format!(
            r"^(?:show|find|locate)\s+(?:the\s+)?(?:(?:{MODIFIERS})\s+)*(?P<name>{NAME})\s+(?:(?!(?:that|which|where|for|and|or)\b)[\w-]+\s+){{0,2}}(?P<kind>{KINDS})\s+(?:definition|declaration)\b"
        ),
        format!(
            r"\b(?:definición|declaración)\s+(?:de\s+la\s+|del\s+|de\s+)?(?P<kind>{KINDS})\s+(?P<name>{NAME})"
        ),
        format!(
            r"^(?:show|find|locate)\s+(?:the\s+)?(?:(?:{MODIFIERS})\s+)*(?P<name>{NAME})\s+(?:[\w]+-[\w-]+\s+){{0,2}}(?P<kind>{KINDS})[.!?]*$"
        ),
        format!(
            r"^(?:mostrame|muestra|busca|buscá|encuentra)\s+(?:(?:el|la)\s+)?(?P<kind>{KINDS})\s+(?P<name>{NAME})(?=\s+(?:para|que)\b|[.!?]*$)"
        ),
    ];
    for (index, pattern) in patterns.iter().enumerate() {
        let Some(m) = p::find(pattern, true, query) else {
            continue;
        };
        if p::has(r"\b(?:and|or|y|o)\b", true, &p::tail(query, m.end)) {
            continue;
        }
        let raw = &m.named["name"];
        let Some(name) = raw_identifier(&p::strip_chars(raw, &[96], true, true)) else {
            continue;
        };
        if BOUNDARIES
            .split_whitespace()
            .any(|b| b == name.to_ascii_lowercase())
        {
            continue;
        }
        let lower = name.bytes().any(|c| c.is_ascii_lowercase())
            && !name.bytes().any(|c| c.is_ascii_uppercase());
        if index >= 2
            && raw.codepoints().first() != Some(&96)
            && lower
            && !name.contains(['_', '.', ':'])
        {
            continue;
        }
        let kind = scalar(&p::fold(&m.named["kind"]));
        let concrete = match kind.as_str() {
            "class" | "clase" => Some("class"),
            "struct" => Some("struct"),
            "interface" => Some("interface"),
            "enum" => Some("enum"),
            "trait" => Some("trait"),
            _ => None,
        }
        .map(str::to_owned);
        return Some((name, concrete));
    }
    None
}
fn requests_tests(query: &PythonText) -> bool {
    let object_query = if let Some(m) = p::find(r"^where\s+(?:is|are)\s+", false, query) {
        let mut points = "find ".chars().map(u32::from).collect::<Vec<_>>();
        points.extend_from_slice(p::tail(query, m.end).codepoints());
        p::text(&points)
    } else {
        query.clone()
    };
    for phrase in [query, &object_query] {
        if let Some(m) = p::find(
            r"^¿?(?:which|what|find|show|locate|qué|que|cuál|busca|buscá|muestra|encuentra|localiza)\s+(?P<modifiers>(?:[\w-]+\s+){0,8}?)(?:tests?|pruebas?|regressions?|regresi[oó]n(?:es)?)\b",
            false,
            phrase,
        ) && phrase.codepoints().get(m.end) != Some(&45)
            && !has_boundary_word(&m.named["modifiers"])
        {
            return true;
        }
    }
    for pattern in [
        r"^where\s+(?:does|do)\s+(?P<object>(?:[\w-]+\s+){0,8})test\s+(?:helpers?|fixtures?|factories|builders?|utilities)\b",
        r"^where\s+(?:is|are)\s+(?P<object>(?:[\w-]+\s+){1,8})tested\s+(?:with|against|using|by|for|when|on)\b",
    ] {
        if let Some(m) = p::find(pattern, false, query)
            && !has_boundary_word(&m.named["object"])
        {
            return true;
        }
    }
    let prefix = if let Some(m) = p::find(r"\b(?:that|which|where|whose)\b", false, &object_query) {
        p::slice(&object_query, 0, m.start)
    } else {
        object_query.clone()
    };
    p::has(r"^(?:find|show|locate)\s+", false, &object_query)
        && p::has(
            r"\b[\w]+-double\s+(?:factory|helper|fixture|builder)\b",
            false,
            &prefix,
        )
        && p::has(r"\btest(?:s|ing)?\b", false, query)
}
pub fn requested_piece_kind(request: &SearchRequest) -> String {
    if let Some(kind) = request.piece_kind() {
        return kind.into();
    }
    if request.target() == "file" {
        return "file".into();
    }
    let mut question = p::strip_chars(&p::fold(request.query()), &[191], true, false);
    if let Some(m) = p::find(r"^(?:which|what|qué|que|cuál|cual)\s+", false, &question) {
        question = p::tail(&question, m.end);
    }
    let prefix = if let Some(m) = p::find(r"\b(?:that|which|que)\b", false, &question) {
        p::slice(&question, 0, m.start)
    } else {
        question
    };
    let mut points = Vec::new();
    for word in p::words(&prefix).iter().take(10) {
        if !points.is_empty() {
            points.push(32);
        }
        points.extend_from_slice(word.codepoints());
    }
    let prefix = p::text(&points);
    match p::find(r"\b(class|clase|module|módulo|modulo|file|archivo|function|función|funcion|method|método|metodo|symbol|símbolo)\b",true,&prefix).map(|m|scalar(&m.whole)).as_deref(){Some("class"|"clase")=>"class",Some("module"|"módulo"|"modulo")=>"module",Some("file"|"archivo")=>"file",_=>"symbol"}.into()
}
pub fn requested_piece_path(request: &SearchRequest) -> Option<PythonText> {
    let query = request.query().clone().trimmed();
    let m = p::find(
        r#"^(?:find|show|locate|open|mostrame|muestra|busca|buscá|encuentra)\s+(?P<path>`[^`]+`|"[^"]+"|[^\s,;]+)"#,
        true,
        &query,
    )?;
    let path = p::strip_chars(&m.named["path"], &[46, 63, 33, 58], false, true);
    let path = p::strip_chars(&path, &[96, 34], true, true);
    let path = p::strip_chars(&path, &[46, 63, 33, 58], false, true);
    (path.codepoints().contains(&47)
        && !path.codepoints().split(|c| *c == 47).any(|v| v == [46, 46]))
    .then_some(path)
}
pub fn interpret(request: &SearchRequest) -> QueryIntent {
    let query = request.query().clone().trimmed();
    let lower = p::fold(&query);
    let purpose = if request.purpose() == "auto" {
        if requests_tests(&lower) {
            "tests"
        } else if p::has(r"\b(?:example|ejemplo)\b", false, &lower) {
            "usage"
        } else {
            "implementation"
        }
    } else {
        request.purpose()
    }
    .to_owned();
    let empty = || QueryIntent {
        purpose: purpose.clone(),
        identity: false,
        identifiers: Vec::new(),
        kind: None,
    };
    if let Some(raw) = raw_identifier(&query) {
        return QueryIntent {
            identifiers: vec![raw],
            ..empty()
        };
    }
    let explicit = p::has(
        r"\b(?:definition|declaration|definición|declaración|defined|declared|defines|declares|definid[oa]|declarad[oa]|declara)\b",
        false,
        &lower,
    ) || (p::has(
        r"^(?:show|find|locate|mostrame|muestra|busca|buscá|encuentra)\b",
        false,
        &lower,
    ) && p::has(&format!(r"\b(?:{KINDS}|función|método)\b"), false, &lower));
    if !explicit {
        return empty();
    }
    let quoted: Vec<_> = p::captures(r"`([^`]+)`", false, &query)
        .into_iter()
        .filter_map(|m| m.groups[1].as_ref().and_then(raw_identifier))
        .collect();
    if quoted.len() <= 1
        && let Some((name, kind)) = named(&query)
    {
        return QueryIntent {
            purpose,
            identity: true,
            identifiers: vec![name],
            kind,
        };
    }
    let stop = "show find locate mostrame muestra busca the a an la el de del of definition declaration definición declaración class clase function función method método helper utility where is defined declared defines declares dónde donde está esta definido definida declarado declarada declara qué que archivo fuente source file";
    let identifiers = if !quoted.is_empty() {
        quoted
    } else {
        p::captures(r"[\w$]+(?:[.:]+[\w$]+)*", false, &query)
            .into_iter()
            .map(|m| scalar(&m.whole))
            .filter(|token| {
                !stop
                    .split_whitespace()
                    .any(|s| s == ken_text::unicode::casefold(token))
            })
            .collect()
    };
    if identifiers.len() != 1 {
        return empty();
    }
    let kind = p::has(r"\b(?:class|clase)\b", false, &lower).then(|| "class".into());
    QueryIntent {
        purpose,
        identity: true,
        identifiers,
        kind,
    }
}
