use ken_program::value::GraphValue;
use ken_query::execution::values::{Value, arithmetic, compare};
fn scalar(text: &str) -> Value {
    Value::literal(text).unwrap()
}
#[test]
fn query_identity_keeps_scalar_and_nested_types_distinct() {
    let values = [
        scalar("true"),
        scalar("1"),
        scalar("1.0"),
        scalar("\"1\""),
        scalar("null"),
    ];
    for (i, a) in values.iter().enumerate() {
        for (j, b) in values.iter().enumerate() {
            assert_eq!(a.identity().unwrap() == b.identity().unwrap(), i == j);
        }
    }
    assert_eq!(
        scalar("-0.0").identity().unwrap(),
        scalar("0.0").identity().unwrap()
    );
    assert_ne!(
        Value::tuple(vec![scalar("true")]).identity().unwrap(),
        Value::tuple(vec![scalar("1")]).identity().unwrap()
    );
    assert_eq!(
        Value::unknown("missing").and(scalar("false")),
        scalar("false")
    );
    assert_eq!(Value::unknown("missing").or(scalar("true")), scalar("true"));
    assert!(Value::unknown("missing").and(scalar("true")).is_unknown());
}
#[test]
fn exact_arithmetic_matches_integer_float_and_python_remainder_contracts() {
    for (a, op, b, expected) in [
        ("9007199254740993", "+", "1", "9007199254740994"),
        (
            "1000000000000000000000000000000000000000000000000000000",
            "*",
            "3",
            "3000000000000000000000000000000000000000000000000000000",
        ),
        ("-5", "%", "3", "1"),
        ("5", "%", "-3", "-1"),
        ("-5.0", "%", "3.0", "1.0"),
        ("5.0", "%", "-3.0", "-1.0"),
        (
            "10000000000000000000000000000000000000000",
            "/",
            "10000000000000000000000000000000000000000",
            "1.0",
        ),
    ] {
        assert_eq!(
            serde_json::to_string(&arithmetic(op, &scalar(a), &scalar(b)).unwrap()).unwrap(),
            expected,
            "{a}{op}{b}"
        );
    }
    assert!(arithmetic("/", &scalar("1"), &scalar("0")).is_err());
    assert!(arithmetic("+", &scalar("true"), &scalar("1")).is_err());
    assert!(
        compare(&scalar("9007199254740993"), &scalar("9007199254740992.0"))
            .unwrap()
            .is_gt()
    );
}
#[test]
fn values_serialize_losslessly_including_surrogates_and_large_integer() {
    for raw in ["1234567890123456789012345678901234567890", r#""\ud800""#] {
        let value = scalar(raw);
        let encoded = serde_json::to_string(&value).unwrap();
        assert_eq!(
            GraphValue::parse(&serde_json::value::RawValue::from_string(encoded).unwrap()).unwrap(),
            GraphValue::parse(&serde_json::value::RawValue::from_string(raw.into()).unwrap())
                .unwrap()
        );
    }
}
#[test]
fn source_snapshot_identity_and_unknown_name_candidates_are_preserved() {
    use ken_query::execution::{GraphRead, MemoryGraph, SourceProbe, values::SourceNode};
    use std::collections::BTreeMap;
    let ir=ken_program::StructuralIr::from_json(r#"{"path":"test.py","language":"python","version":"1.88.0","view":"query","entities":{"x":{"id":"x","kind":"CALLABLE","name":"target","path":"test.py","line":1,"end_line":2,"attrs":{}}},"operations":[],"facts":[],"capabilities":[],"diagnostics":[],"relations":[]}"#).unwrap();
    let graph = MemoryGraph::new(&ir).unwrap();
    assert_eq!(graph.source_node("x").unwrap().unwrap().id, 0);
    let named = SourceNode {
        id: 11,
        unit: 7,
        local_id: "x".into(),
        kind: "CALLABLE".into(),
        name: Some("target".into()),
        owner: None,
        line: 1,
        end_line: 2,
        path: "test.py".into(),
        language: "python".into(),
    };
    let unknown = SourceNode {
        id: 12,
        local_id: "unknown".into(),
        name: None,
        ..named.clone()
    };
    let graph = graph
        .with_source_nodes(vec![named, unknown], BTreeMap::new(), BTreeMap::new(), true)
        .with_source_snapshot_id(9);
    let mut found = vec![];
    graph
        .source_scan(
            &SourceProbe {
                kind: Some("CALLABLE".into()),
                name: Some("target".into()),
                ..Default::default()
            },
            &mut || Ok(()),
            &mut |n| {
                found.push(n.local_id.clone());
                Ok(())
            },
        )
        .unwrap();
    assert_eq!(found, ["x", "unknown"]);
    assert_eq!(graph.source_snapshot_id(), 9);
    assert!(graph.source_coverage().unwrap());
    let mut units = vec![];
    graph
        .source_units(&mut || Ok(()), &mut |unit| {
            units.push(unit);
            Ok(())
        })
        .unwrap();
    assert_eq!(units, [7]);
}
#[test]
fn host_json_numbers_do_not_round_large_query_integers() {
    let digits = "9".repeat(500);
    let value = Value::integer(&digits);
    let encoded = serde_json::to_string(&value).unwrap();
    assert_eq!(encoded, digits);
    let host: serde_json::Value = serde_json::from_str(&encoded)
        .expect("host JSON must accept finite arbitrary-size query integers");
    assert_eq!(host.as_number().unwrap().to_string(), digits);
    let surrogate = Value::literal(r#""\ud800""#).unwrap();
    assert_eq!(serde_json::to_string(&surrogate).unwrap(), r#""\ud800""#);
}
#[test]
fn query_json_literals_join_utf16_pairs_without_changing_historical_text_codec() {
    let raw = r#""\ud83d\ude00""#;
    let historical: ken_text::PythonText = serde_json::from_str(raw).unwrap();
    assert_eq!(historical.codepoints(), [0xd83d, 0xde00]);
    assert_eq!(Value::literal(raw).unwrap().text().as_deref(), Some("😀"));
    assert_eq!(
        serde_json::from_str::<ken_text::PythonText>(r#""\ud800x""#)
            .unwrap()
            .joined_surrogates()
            .codepoints(),
        [0xd800, 120]
    );
    let tree = ken_query::parse(
        r#"language "kql/2";module pair;query q{select "\ud800", "\ud83d\ude00";}"#,
        "surrogate-literal",
        Default::default(),
    )
    .unwrap();
    let program = ken_query::compile_indexed(&tree, None).unwrap();
    let graph=ken_query::execution::MemoryGraph::new(&ken_program::StructuralIr::from_json(r#"{"path":"","language":"","version":"1.88.0","view":"query","entities":{},"operations":[],"facts":[],"capabilities":[],"diagnostics":[],"relations":[]}"#).unwrap()).unwrap();
    let out = ken_query::execution::indexed_runtime::IndexedExecution::new(Default::default())
        .unwrap()
        .execute(&graph, &program)
        .unwrap();
    assert!(out.complete);
    assert_eq!(
        serde_json::to_string(&out.rows[0]).unwrap(),
        "[\"\\ud800\",\"😀\"]"
    );
}
#[test]
fn string_literals_do_not_inherit_the_large_integer_digit_limit() {
    let text = "x".repeat(100_000);
    let raw = serde_json::to_string(&text).unwrap();
    assert_eq!(Value::literal(&raw).unwrap().text().unwrap(), text);
}
