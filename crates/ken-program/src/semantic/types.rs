//! Annotation syntax descriptors; they never establish runtime nominal identity.
use super::*;
use serde::Serialize;
use sha2::{Digest, Sha256};
#[derive(Clone, Serialize)]
struct TypeRef {
    kind: String,
    native: String,
    arguments: Vec<TypeRef>,
    bits: Option<u16>,
    signed: Option<bool>,
    extent: Option<String>,
    rank: Option<usize>,
    qualifiers: Vec<String>,
}
impl TypeRef {
    fn new(kind: &str, text: &str) -> Self {
        Self {
            kind: kind.into(),
            native: text.into(),
            arguments: vec![],
            bits: None,
            signed: None,
            extent: None,
            rank: None,
            qualifiers: vec![],
        }
    }
    fn wrap(kind: &str, text: &str, args: Vec<Self>) -> Self {
        Self {
            arguments: args,
            ..Self::new(kind, text)
        }
    }
}
fn split(text: &str, separator: char) -> Vec<&str> {
    let (mut depth, mut start) = (0, 0);
    let mut parts = vec![];
    for (i, c) in text.char_indices() {
        match c {
            '<' | '[' | '(' => depth += 1,
            '>' | ']' | ')' => depth -= 1,
            _ if c == separator && depth == 0 => {
                parts.push(trim(&text[start..i]));
                start = i + c.len_utf8();
            }
            _ => {}
        }
    }
    parts.push(trim(&text[start..]));
    parts
}
fn parse(annotation: &str, lang: &str, depth: usize) -> TypeRef {
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
    let child = |t: &str| parse(t, lang, depth + 1);
    let union = split(text, '|');
    if union.len() > 1 {
        return TypeRef::wrap("union", text, union.into_iter().map(child).collect());
    }
    if matches!(lang, "csharp" | "typescript")
        && let Some(inner) = text.strip_suffix('?')
    {
        return TypeRef::wrap("optional", text, vec![child(inner)]);
    }
    if lang == "rust" && text.starts_with('&') {
        let r = rx(r"^&\s*(?:'[a-zA-Z_]\w*\s*)?(?:mut\s+)?");
        let inner = r.replace(text, "");
        return TypeRef::wrap("reference", text, vec![child(&inner)]);
    }
    if matches!(lang, "cpp" | "go")
        && let Some(inner) = text.strip_prefix('*')
    {
        return TypeRef::wrap("pointer", text, vec![child(inner)]);
    }
    if lang == "cpp" {
        if !text.ends_with('>') && rx(r"\([^)]*[*&]").is_match(text) {
            return TypeRef::new("opaque", text);
        }
        if let Some(m) = full(r"(.+?)(?:\s+|([*&]))((?:(?:const|volatile)\s*)+)", text) {
            let head = format!("{}{}", &m[1], m.get(2).map_or("", |m| m.as_str()));
            let mut r = TypeRef::wrap("qualified", text, vec![child(&head)]);
            r.qualifiers = m[3]
                .split(ken_text::unicode::whitespace)
                .filter(|s| !s.is_empty())
                .map(Into::into)
                .collect();
            return r;
        }
        if let Some(inner) = text.strip_suffix("&&") {
            return TypeRef::wrap("rvalue_reference", text, vec![child(inner)]);
        }
        if text.ends_with(['*', '&']) {
            return TypeRef::wrap(
                if text.ends_with('*') {
                    "pointer"
                } else {
                    "reference"
                },
                text,
                vec![child(&text[..text.len() - 1])],
            );
        }
    }
    if lang == "go" && text.starts_with("map[") {
        let mut nesting = 1;
        for (i, c) in text.char_indices().filter(|(i, _)| *i >= 4) {
            nesting += i32::from(c == '[') - i32::from(c == ']');
            if nesting == 0 {
                return TypeRef::wrap("map", text, vec![child(&text[4..i]), child(&text[i + 1..])]);
            }
        }
    }
    if lang == "go"
        && let Some(m) = full(r"\[([^\]]*)\](.+)", text)
    {
        let mut r = TypeRef::wrap(
            if m[1].is_empty() { "slice" } else { "array" },
            text,
            vec![child(&m[2])],
        );
        r.extent = (!m[1].is_empty()).then(|| m[1].into());
        return r;
    }
    if lang == "rust" && text.starts_with('[') && text.ends_with(']') {
        let parts = split(&text[1..text.len() - 1], ';');
        if matches!(parts.len(), 1 | 2) {
            let mut r = TypeRef::wrap(
                if parts.len() == 2 { "array" } else { "slice" },
                text,
                vec![child(parts[0])],
            );
            r.extent = parts.get(1).map(|x| (*x).into());
            return r;
        }
    }
    if lang == "cpp"
        && let Some(m) = full(r"((?:(?:const|volatile)\s+)+)(.+)", text)
    {
        let mut r = TypeRef::wrap("qualified", text, vec![child(&m[2])]);
        r.qualifiers = m[1]
            .split(ken_text::unicode::whitespace)
            .filter(|s| !s.is_empty())
            .map(Into::into)
            .collect();
        return r;
    }
    if matches!(
        lang,
        "javascript" | "typescript" | "java" | "csharp" | "cpp"
    ) && let Some(m) = full(r"(.+)\[([,\d\s]*)\]", text)
    {
        let mut r = TypeRef::wrap("array", text, vec![child(&m[1])]);
        if lang == "csharp" {
            r.rank = Some(m[2].matches(',').count() + 1);
        } else {
            r.extent = (!trim(&m[2]).is_empty()).then(|| trim(&m[2]).into());
        }
        return r;
    }
    if let Some(m) = full(r"([\w.:]+)\s*[<\[](.+)[>\]]", text) {
        let base = m[1]
            .rsplit("::")
            .next()
            .unwrap()
            .rsplit('.')
            .next()
            .unwrap();
        let arguments = split(&m[2], ',').into_iter().map(child).collect::<Vec<_>>();
        if lang == "cpp" && base == "array" && arguments.len() == 2 {
            let mut r = TypeRef::wrap("array", text, vec![arguments[0].clone()]);
            r.extent = Some(arguments[1].native.clone());
            return r;
        }
        let kind = match base {
            "list" | "List" | "Vec" | "vector" => "list",
            "Array" | "array" => "array",
            "dict" | "Dict" | "Map" | "HashMap" | "Dictionary" | "map" | "unordered_map" => "map",
            "set" | "Set" | "HashSet" => "set",
            "tuple" | "Tuple" => "tuple",
            "Optional" | "Option" => "optional",
            "Union" => "union",
            _ => "generic",
        };
        return TypeRef::wrap(kind, text, arguments);
    }
    if text.starts_with('(') && text.ends_with(')') && text.contains(',') {
        return TypeRef::wrap(
            "tuple",
            text,
            split(&text[1..text.len() - 1], ',')
                .into_iter()
                .filter(|x| !x.is_empty())
                .map(child)
                .collect(),
        );
    }
    let kind = match text {
        "list" | "dict" | "set" | "tuple" if lang == "python" => {
            if text == "dict" {
                "map"
            } else {
                text
            }
        }
        "any" | "Any" | "dynamic" => "any",
        "never" | "Never" | "NoReturn" => "never",
        "None" | "NoneType" | "null" | "nil" => "null",
        "void" => "void",
        "bool" | "boolean" | "Boolean" => "bool",
        "str" | "string" | "String" | "std::string" => "str",
        "number" => "number",
        _ => "",
    };
    if !kind.is_empty() {
        return TypeRef::new(kind, text);
    }
    if matches!(text, "char" | "wchar_t" | "char16_t" | "char32_t") {
        let mut r = TypeRef::new("char", text);
        r.bits = if (text == "char" && matches!(lang, "java" | "csharp")) || text == "char16_t" {
            Some(16)
        } else if text == "char32_t" || (text == "char" && lang == "rust") {
            Some(32)
        } else {
            None
        };
        return r;
    }
    for (pattern, signed) in [
        (r"([iu])(8|16|32|64|128)", true),
        (r"(u?)int(8|16|32|64)(?:_t)?", false),
    ] {
        if let Some(m) = full(pattern, text) {
            let mut r = TypeRef::new("int", text);
            r.bits = m[2].parse().ok();
            r.signed = Some(if signed {
                &m[1] == "i"
            } else {
                m[1].is_empty()
            });
            return r;
        }
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
        let mut r = TypeRef::new("int", text);
        r.bits = if matches!(lang, "java" | "csharp") {
            match text {
                "int" | "uint" => Some(32),
                "long" | "ulong" => Some(64),
                "short" | "ushort" => Some(16),
                "byte" | "sbyte" => Some(8),
                _ => None,
            }
        } else if text == "rune" {
            Some(32)
        } else if text == "byte" && lang == "go" {
            Some(8)
        } else {
            None
        };
        r.signed = (lang != "python").then(|| {
            !(text.starts_with('u') || (text == "byte" && matches!(lang, "csharp" | "go")))
        });
        return r;
    }
    if matches!(
        text,
        "float" | "double" | "f32" | "f64" | "float32" | "float64"
    ) {
        let mut r = TypeRef::new("float", text);
        r.bits = if matches!(text, "f32" | "float32")
            || (text == "float" && matches!(lang, "java" | "csharp"))
        {
            Some(32)
        } else if matches!(text, "f64" | "float64")
            || (text == "double" && matches!(lang, "java" | "csharp"))
        {
            Some(64)
        } else {
            None
        };
        return r;
    }
    TypeRef::new(
        if full(r"[\w.:]+", text).is_some() {
            "nominal"
        } else {
            "opaque"
        },
        text,
    )
}
fn py_json(v: &Value) -> String {
    match v {
        Value::String(s) => {
            let mut out = String::from("\"");
            for c in s.chars() {
                match c {
                    '"' => out.push_str("\\\""),
                    '\\' => out.push_str("\\\\"),
                    '\n' => out.push_str("\\n"),
                    '\r' => out.push_str("\\r"),
                    '\t' => out.push_str("\\t"),
                    '\u{8}' => out.push_str("\\b"),
                    '\u{c}' => out.push_str("\\f"),
                    c if !(' '..='~').contains(&c) => {
                        let mut buf = [0; 2];
                        for unit in c.encode_utf16(&mut buf) {
                            out.push_str(&format!("\\u{unit:04x}"));
                        }
                    }
                    c => out.push(c),
                }
            }
            out.push('"');
            out
        }
        Value::Array(a) => format!("[{}]", a.iter().map(py_json).collect::<Vec<_>>().join(", ")),
        Value::Object(m) => format!(
            "{{{}}}",
            m.iter()
                .map(|(k, v)| format!("{}: {}", py_json(&Value::String(k.clone())), py_json(v)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
        _ => v.to_string(),
    }
}
fn materialize(
    g: &mut Graph,
    r: &TypeRef,
    language: &str,
    existing: &mut BTreeSet<String>,
) -> Result<String> {
    let encoded = py_json(&json!([language, r]));
    let key = format!("type-ref:{:x}", Sha256::digest(encoded.as_bytes()));
    if !existing.insert(key.clone()) {
        return Ok(key);
    }
    g.add(
        &key,
        "TYPE_KIND",
        &r.kind,
        "",
        json!({"basis":"annotation-syntax"}),
    );
    g.add(
        &key,
        "TYPE_NATIVE",
        &r.native,
        "",
        json!({"basis":"annotation-syntax"}),
    );
    if let Some(v) = r.bits {
        g.add(&key, "TYPE_BITS", &v.to_string(), "", json!({}));
    }
    if let Some(v) = r.signed {
        g.add(&key, "TYPE_SIGNED", &v.to_string(), "", json!({}));
    }
    if let Some(v) = &r.extent {
        g.add(&key, "TYPE_EXTENT", v, "", json!({}));
    }
    if let Some(v) = r.rank {
        g.add(&key, "TYPE_RANK", &v.to_string(), "", json!({}));
    }
    for v in &r.qualifiers {
        g.add(
            &key,
            "TYPE_QUALIFIER",
            v,
            "",
            json!({"basis":"annotation-syntax"}),
        );
    }
    for (i, arg) in r.arguments.iter().enumerate() {
        let target = materialize(g, arg, language, existing)?;
        g.add(&key, "TYPE_ARGUMENT", &target, "", json!({"position":i}));
    }
    Ok(key)
}
pub(super) fn annotation_types(g: &mut Graph) -> Result<()> {
    let mut existing = BTreeSet::new();
    for id in g.ids() {
        let e = g.e(&id)?.clone();
        let language = s(&e.attrs, "language")?;
        let literal = if e.kind == "COLLECTION" {
            s(&e.attrs, "collection_kind")?
        } else if e.kind == "VALUE" {
            s(&e.attrs, "type")?
        } else {
            String::new()
        };
        let evidence = g.evidence(&id)?;
        if matches!(
            literal.as_str(),
            "int"
                | "float"
                | "str"
                | "char"
                | "bool"
                | "number"
                | "array"
                | "list"
                | "map"
                | "record"
        ) {
            let r = TypeRef::new(&literal, &s(&e.attrs, "native_kind")?);
            let target = materialize(g, &r, &language, &mut existing)?;
            g.add(
                &id,
                "TYPE_REF",
                &target,
                &evidence,
                json!({"basis":"literal-syntax"}),
            );
        }
        for (attribute, relation) in [
            ("native_type", "TYPE_REF"),
            ("native_return_type", "RETURN_TYPE_REF"),
        ] {
            let annotation = v(&e.attrs, attribute)?;
            let missing = annotation.is_null()
                && ((attribute == "native_type"
                    && matches!(e.kind.as_str(), "PARAMETER" | "STORAGE"))
                    || (attribute == "native_return_type" && e.kind == "CALLABLE"));
            if annotation.is_string() || missing {
                let text = annotation.as_str().unwrap_or("");
                let r = parse(text, &language, 0);
                let target = materialize(g, &r, &language, &mut existing)?;
                g.add(&id,relation,&target,&evidence,json!({"basis":if text.is_empty(){"missing-annotation"}else{"annotation-syntax"}}));
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod reference_tests {
    use super::*;
    use flate2::read::GzDecoder;
    use std::io::Read;
    #[test]
    fn original_annotation_descriptors_hashes_unicode_and_bounds_match() {
        let bytes = include_bytes!("../../tests/fixtures/annotation-types-reference.json.gz");
        assert_eq!(bytes.len(), 159570);
        assert_eq!(
            format!("{:x}", Sha256::digest(bytes)),
            "f91717f82cfebaeaeb8b947b64332169b4bc314286e90d2d4f333c6a5b454428"
        );
        let mut text = String::new();
        GzDecoder::new(&bytes[..])
            .read_to_string(&mut text)
            .unwrap();
        let corpus: Value = serde_json::from_str(&text).unwrap();
        let cases = corpus["cases"].as_array().unwrap();
        assert_eq!(cases.len(), 639);
        let mut errors = Vec::new();
        for c in cases {
            let language = c["language"].as_str().unwrap();
            let text = c["annotation"].as_str().unwrap();
            if serde_json::to_value(parse(text, language, 0)).unwrap() != c["parsed"] {
                errors.push(format!("{language}: {text:?}"));
                continue;
            }
            let mut ir = StructuralIr::from_json(&c["result"].to_string()).unwrap();
            ir.facts.clear();
            ir.relations.clear();
            let mut g = Graph::new(ir).unwrap();
            annotation_types(&mut g).unwrap();
            assert_eq!(
                serde_json::to_value(g.ir).unwrap(),
                c["result"],
                "{language}: {text:?}"
            );
        }
        assert!(errors.is_empty(), "{}", errors.join("\n"));
    }
}
