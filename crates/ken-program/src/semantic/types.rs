//! Materialize the shared annotation descriptor model as evidence-bearing facts.
use super::*;
use crate::{TypeRef, parse_type};
use sha2::{Digest, Sha256};
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
                let r = parse_type(text, &language);
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
            if serde_json::to_value(crate::parse_type(text, language)).unwrap() != c["parsed"] {
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
