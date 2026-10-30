use flate2::read::GzDecoder;
use serde_json::{Value, json};
use sha2::Digest;
use std::io::Read;
fn normalize(value: Value) -> Value {
    match value {
        Value::Array(values) => Value::Array(values.into_iter().map(normalize).collect()),
        Value::Object(mut values) => {
            if values.contains_key("mode") && values.contains_key("relation") {
                values.retain(|k, _| {
                    ["mode", "subject", "relation", "object", "attrs"].contains(&k.as_str())
                });
            }
            match values
                .remove("__class__")
                .and_then(|v| v.as_str().map(str::to_owned))
                .as_deref()
            {
                Some("OrderedMap") => values
                    .remove("items")
                    .unwrap()
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|pair| {
                        (
                            pair[0].as_str().unwrap().to_owned(),
                            normalize(pair[1].clone()),
                        )
                    })
                    .collect(),
                Some("QuotedTerm") => json!({"literal":values.remove("literal").unwrap()}),
                _ => Value::Object(values.into_iter().map(|(k, v)| (k, normalize(v))).collect()),
            }
        }
        other => other,
    }
}
#[test]
fn original_legacy_blocks_selectors_and_relational_conversion_match() {
    let bytes = include_bytes!("fixtures/legacy-blocks-reference.json.gz");
    assert_eq!(bytes.len(), 3073);
    assert_eq!(
        format!("{:x}", sha2::Sha256::digest(bytes)),
        "6c37611a13d3112a845248598a268f4b42516651b55b6172aab083a1c0436a0b"
    );
    let mut raw = String::new();
    GzDecoder::new(&bytes[..]).read_to_string(&mut raw).unwrap();
    let data: Value = serde_json::from_str(&raw).unwrap();
    for c in data["cases"].as_array().unwrap() {
        let source = c["source"].as_str().unwrap();
        let parsed = if c["kind"] == "block" {
            ken_query::legacy_blocks::parse(source)
                .map(|p| normalize(serde_json::to_value(p).unwrap()))
        } else {
            ken_query::legacy::parse_query(source)
                .map(|p| normalize(serde_json::to_value(p).unwrap()))
        };
        if let Some(error) = c.get("error") {
            assert_eq!(
                parsed.unwrap_err().to_string(),
                error.as_str().unwrap(),
                "{}",
                c["name"]
            );
        } else {
            assert_eq!(parsed.unwrap(), c["parsed"], "{}", c["name"]);
        }
        if c["kind"] == "selectors" && c.get("parsed").is_some() {
            let converted = ken_query::legacy_blocks::legacy_query(source, "selected");
            if let Some(error) = c.get("relational_error") {
                assert_eq!(
                    converted.unwrap_err().to_string(),
                    error.as_str().unwrap(),
                    "{}",
                    c["name"]
                );
            } else {
                assert_eq!(
                    normalize(serde_json::to_value(converted.unwrap()).unwrap()),
                    c["relational"],
                    "{}",
                    c["name"]
                );
            }
        }
    }
}
#[test]
fn parsed_legacy_blocks_execute_through_the_shared_relational_engine() {
    use ken_query::execution::{Execution, MemoryGraph};
    let graph=ken_program::StructuralIr::from_json(r#"{"path":"legacy.py","language":"python","version":"1.88.0","view":"query","entities":{},"operations":[],"facts":[{"subject":"A","relation":"ENTITY","object":"CLASS","attrs":{"name":"A"},"evidence":["class"]},{"subject":"A","relation":"HAS_METHOD","object":"go","attrs":{},"evidence":["member"]},{"subject":"go","relation":"ENTITY","object":"CALLABLE","attrs":{"name":"go"},"evidence":["method"]}],"capabilities":[],"diagnostics":[],"relations":[]}"#).unwrap();
    let graph = MemoryGraph::new(&graph).unwrap();
    let query = ken_query::legacy_blocks::parse(
        "query selected {class(name:\"A\") as $c {has_method(name:\"go\") as $f;}emit $c,$f;}",
    )
    .unwrap();
    let out = Execution::new(Default::default())
        .unwrap()
        .execute(&graph, &query)
        .unwrap();
    assert!(out.complete);
    assert_eq!(out.matches.len(), 1);
    assert_eq!(out.matches[0].bindings["$c"], "A");
    assert_eq!(out.matches[0].bindings["$f"], "go");
    assert_eq!(out.matches[0].evidence.len(), 3);
}
