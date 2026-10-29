use flate2::read::GzDecoder;
use ken_query::{
    ParseError, ParseLimits, PythonRepr, ast::*, parse, parse_bytes, resolve_libraries,
    specialize_models,
};
use serde::Deserialize;
use serde_json::{Value, value::RawValue};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, io::Read};
#[derive(Deserialize)]
struct Fixture {
    cases: Vec<Case>,
    snapshots: Vec<Value>,
}
#[derive(Deserialize)]
struct Case {
    name: String,
    text: Box<RawValue>,
    source: String,
    limits: Value,
    tree: Option<Box<RawValue>>,
    repr: Option<String>,
    error: Option<ParseError>,
    prepared: Option<Box<RawValue>>,
    prepared_repr: Option<String>,
    preparation_error: Option<ParseError>,
}
fn fixture() -> Fixture {
    let bytes = include_bytes!("fixtures/frontend-reference.json.gz");
    assert_eq!(bytes.len(), 141735);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "4657e2d18f5bd423240353b877f8e9bfc3137aaaf255fe195b59e68fbf3d2b82"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    let mut decoder = serde_json::Deserializer::from_str(&text);
    decoder.disable_recursion_limit();
    Fixture::deserialize(&mut decoder).unwrap()
}
fn json(raw: &RawValue) -> Value {
    let mut d = serde_json::Deserializer::from_str(raw.get());
    d.disable_recursion_limit();
    Value::deserialize(&mut d).unwrap()
}
fn large_stack(task: impl FnOnce() + Send + 'static) {
    std::thread::Builder::new()
        .stack_size(64 * 1024 * 1024)
        .spawn(task)
        .unwrap()
        .join()
        .unwrap()
}
fn difference(a: &Value, b: &Value, path: &str) -> Option<String> {
    if a == b {
        return None;
    }
    match (a, b) {
        (Value::Object(a), Value::Object(b)) => {
            for k in a.keys().chain(b.keys()) {
                if let (Some(a), Some(b)) = (a.get(k), b.get(k)) {
                    if let Some(d) = difference(a, b, &format!("{path}/{k}")) {
                        return Some(d);
                    }
                } else {
                    return Some(format!("{path}/{k}: missing field"));
                }
            }
        }
        (Value::Array(a), Value::Array(b)) => {
            if a.len() != b.len() {
                return Some(format!("{path}: lengths {} != {}", a.len(), b.len()));
            }
            for (i, (a, b)) in a.iter().zip(b).enumerate() {
                if let Some(d) = difference(a, b, &format!("{path}/{i}")) {
                    return Some(d);
                }
            }
        }
        _ => return Some(format!("{path}: {a} != {b}")),
    }
    Some(path.into())
}
#[test]
fn complete_typed_original_syntax_and_diagnostics_match() {
    large_stack(|| {
        let cases = fixture().cases;
        assert_eq!(cases.len(), 574);
        let mut errors = vec![];
        for c in cases {
            let text = ken_program::value::GraphValue::parse(&c.text)
                .unwrap()
                .string();
            let mut limits = ParseLimits::default();
            if let Some(v) = c.limits.get("max_depth").and_then(Value::as_u64) {
                limits.max_depth = v as usize;
            }
            if let Some(v) = c.limits.get("max_bytes").and_then(Value::as_u64) {
                limits.max_bytes = v as usize;
            }
            let result = text.as_ref().map_or_else(
                || parse_bytes(&[0xff], &c.source, limits),
                |s| parse(s, &c.source, limits),
            );
            match (result, c.error) {
                (Err(got), Some(want)) => {
                    if c.name == "depth/type/600" {
                        let input = text.as_ref().unwrap();
                        assert_eq!(got.span.source.as_ref(), c.source);
                        assert!(got.span.start <= got.span.end && got.span.end <= input.len());
                        assert!(input.is_char_boundary(got.span.start));
                        assert!(input.is_char_boundary(got.span.end));
                        if got.code != want.code || got.message != want.message {
                            errors.push(format!("{}: {got:?} != {want:?}", c.name));
                        }
                    } else if got != want {
                        errors.push(format!("{}: {got:?} != {want:?}", c.name));
                    }
                }
                (Ok(tree), None) => {
                    let got = serde_json::to_value(&tree).unwrap();
                    let want = json(c.tree.as_ref().unwrap());
                    if let Some(d) = difference(&got, &want, "") {
                        errors.push(format!("AST {}: {d}", c.name));
                    } else if tree.python_repr() != c.repr.unwrap() {
                        errors.push(format!("repr {}", c.name));
                    }
                }
                (Ok(_), Some(want)) => {
                    errors.push(format!("{}: succeeded but expected {want:?}", c.name))
                }
                (Err(got), None) => errors.push(format!("{}: unexpected {got:?}", c.name)),
            }
        }
        assert!(
            errors.is_empty(),
            "{} mismatches:\n{}",
            errors.len(),
            errors
                .iter()
                .take(40)
                .cloned()
                .collect::<Vec<_>>()
                .join("\n")
        );
    })
}
#[test]
fn original_module_qualification_and_model_specialization_match() {
    large_stack(|| {
        let f = fixture();
        for c in f.cases {
            let Some(raw) = c.tree else { continue };
            let mut d = serde_json::Deserializer::from_str(raw.get());
            d.disable_recursion_limit();
            let tree = File::deserialize(&mut d).unwrap();
            let result =
                resolve_libraries(&tree, &BTreeMap::new()).and_then(|t| specialize_models(&t));
            match (result, c.preparation_error) {
                (Ok(got), None) => {
                    assert_eq!(
                        serde_json::to_value(&got).unwrap(),
                        json(c.prepared.as_ref().unwrap()),
                        "prepared {}",
                        c.name
                    );
                    assert_eq!(
                        got.python_repr(),
                        c.prepared_repr.unwrap(),
                        "prepared repr {}",
                        c.name
                    );
                }
                (Err(got), Some(want)) => assert_eq!(got, want, "prepare {}", c.name),
                (got, want) => panic!("prepare {}: {got:?} vs {want:?}", c.name),
            }
        }
        for s in f.snapshots {
            let name = s["name"].as_str().unwrap();
            let entry = parse(s["entry"].as_str().unwrap(), name, ParseLimits::default()).unwrap();
            let libraries = s["libraries"]
                .as_object()
                .unwrap()
                .iter()
                .map(|(k, v)| {
                    (
                        k.clone(),
                        parse(v.as_str().unwrap(), k, ParseLimits::default()).unwrap(),
                    )
                })
                .collect();
            let result = resolve_libraries(&entry, &libraries).and_then(|resolved| {
                assert_eq!(serde_json::to_value(&resolved).unwrap(), s["resolved"]);
                assert_eq!(resolved.python_repr(), s["resolved_repr"].as_str().unwrap());
                specialize_models(&resolved)
            });
            if s.get("error").is_some() {
                assert_eq!(
                    serde_json::to_value(result.unwrap_err()).unwrap(),
                    s["error"],
                    "{name}"
                );
            } else {
                let got = result.unwrap();
                assert_eq!(serde_json::to_value(&got).unwrap(), s["prepared"], "{name}");
                assert_eq!(got.python_repr(), s["prepared_repr"].as_str().unwrap());
            }
        }
    })
}
#[test]
fn source_and_query_nodes_remain_distinct_with_byte_spans() {
    let text = "language \"kql/2\"; module test; pattern P() { bind $n = 2; body { let $x = -$y ** 2; call $f {argument $x at 0;}; $x = 1; } }";
    let tree = parse(text, "é🙂", ParseLimits::default()).unwrap();
    let clauses = &tree.declarations[0].clauses;
    assert!(matches!(clauses[0].expressions[0], Expression::Query(_)));
    assert!(matches!(
        clauses[1].blocks[0][0].expressions[0],
        Expression::Source(_)
    ));
    for c in &clauses[1].blocks[0] {
        assert!(text.is_char_boundary(c.span.start));
        assert!(text.is_char_boundary(c.span.end));
    }
}
#[test]
fn original_alternative_expansion_and_predicate_components_match() {
    large_stack(|| {
        #[derive(Deserialize)]
        struct Corpus {
            cases: Vec<ExpansionCase>,
        }
        #[derive(Deserialize)]
        struct ExpansionCase {
            name: String,
            tree: Box<RawValue>,
            result: Option<Box<RawValue>>,
            repr: Option<String>,
            error: Option<ParseError>,
            components: Option<Vec<Vec<String>>>,
            components_error: Option<ParseError>,
        }
        let bytes = include_bytes!("fixtures/expansion-reference.json.gz");
        assert_eq!(bytes.len(), 85658);
        assert_eq!(
            format!("{:x}", Sha256::digest(bytes)),
            "b996a940cd6727775494fa26a62c3f37991bc722caa9f4293cc742a3504f470c"
        );
        let mut text = String::new();
        GzDecoder::new(&bytes[..])
            .read_to_string(&mut text)
            .unwrap();
        let mut d = serde_json::Deserializer::from_str(&text);
        d.disable_recursion_limit();
        let corpus = Corpus::deserialize(&mut d).unwrap();
        assert_eq!(corpus.cases.len(), 227);
        for c in corpus.cases {
            let mut d = serde_json::Deserializer::from_str(c.tree.get());
            d.disable_recursion_limit();
            let tree = File::deserialize(&mut d).unwrap();
            match (ken_query::expand_indexed_alternatives(&tree, None), c.error) {
                (Ok(got), None) => {
                    assert_eq!(
                        serde_json::to_value(&got).unwrap(),
                        json(c.result.as_ref().unwrap()),
                        "expansion {}",
                        c.name
                    );
                    assert_eq!(
                        got.python_repr(),
                        c.repr.unwrap(),
                        "expansion repr {}",
                        c.name
                    );
                }
                (Err(got), Some(want)) => assert_eq!(got, want, "expansion {}", c.name),
                (got, want) => panic!("expansion {}: {got:?} vs {want:?}", c.name),
            }
            let predicates: Vec<_> = tree
                .declarations
                .iter()
                .filter(|d| d.kind == "predicate")
                .filter_map(|d| {
                    d.formula.as_ref().map(|f| ken_query::Predicate {
                        name: d.name.clone(),
                        parameters: d.parameters.clone(),
                        formula: f.clone(),
                    })
                })
                .collect();
            match (
                ken_query::predicate_components(&predicates),
                c.components_error,
            ) {
                (Ok(got), None) => assert_eq!(got, c.components.unwrap(), "components {}", c.name),
                (Err(got), Some(want)) => assert_eq!(got, want, "components {}", c.name),
                (got, want) => panic!("components {}: {got:?} vs {want:?}", c.name),
            }
        }
    })
}
#[test]
fn native_byte_limits_ast_limits_and_deep_types_have_bounded_errors() {
    assert_eq!(
        parse_bytes(&[0xff], "bytes", ParseLimits::default())
            .unwrap_err()
            .span
            .start,
        0
    );
    let text = "language \"kql/2\"; module limit; query q{select 1;}";
    let err = parse(
        text,
        "bytes",
        ParseLimits {
            max_bytes: 4,
            ..Default::default()
        },
    )
    .unwrap_err();
    assert_eq!(err.code, "resource_limit");
    assert_eq!(err.span.end, text.len());
    let input = format!(
        "language \"kql/2\"; module deep; pattern P(){{field $f{{type:{}int{};}}}}",
        "T<".repeat(400),
        ">".repeat(400)
    );
    let tree = parse(&input, "deep", ParseLimits::default()).unwrap();
    assert!(resolve_libraries(&tree, &BTreeMap::new()).is_ok());
    assert!(tree.python_repr().contains("source_type"));
    let flat = format!(
        "language \"kql/2\"; module flat; query q{{select {};}}",
        vec!["1"; 5000].join("+")
    );
    let error = parse(&flat, "flat", ParseLimits::default()).unwrap_err();
    assert_eq!(error.code, "resource_limit");
    assert!(error.span.end <= flat.len());
}
#[test]
fn module_resolution_uses_iterative_dependency_order_and_does_not_modify_inputs() {
    let root = parse(
        "language \"kql/2\"; module root; import m0; query q{select 1;}",
        "root",
        ParseLimits::default(),
    )
    .unwrap();
    let mut libraries = BTreeMap::new();
    for i in 0..2000 {
        let next = if i < 1999 {
            format!("import m{};", i + 1)
        } else {
            String::new()
        };
        let text = format!("language \"kql/2\"; module m{i}; {next} pattern P{i}(){{}}");
        libraries.insert(
            format!("m{i}"),
            parse(&text, "lib", ParseLimits::default()).unwrap(),
        );
    }
    let before = serde_json::to_string(&root).unwrap();
    let result = resolve_libraries(&root, &libraries).unwrap();
    assert_eq!(result.declarations.len(), 2001);
    assert_eq!(result.declarations[0].name, "m1999.P1999");
    assert_eq!(result.declarations[1999].name, "m0.P0");
    assert_eq!(serde_json::to_string(&root).unwrap(), before);
}
#[test]
fn predicate_component_analysis_handles_long_chains_without_recursive_graph_walks() {
    let span = Span {
        source: "chain".into(),
        start: 0,
        end: 0,
    };
    let mut predicates = vec![];
    for i in 0..10000 {
        let formula = ken_query::ast::Expr::checked(
            if i == 9999 { "literal" } else { "call" }.into(),
            span.clone(),
            if i == 9999 {
                "true".into()
            } else {
                format!("p{}", i + 1)
            },
            vec![],
            vec![],
        )
        .unwrap();
        predicates.push(ken_query::Predicate {
            name: format!("p{i}"),
            parameters: vec![],
            formula,
        });
    }
    let result = ken_query::predicate_components(&predicates).unwrap();
    assert_eq!(result.len(), 10000);
}
#[test]
fn contextual_regex_generated_corpus_matches_original_diagnostics() {
    large_stack(|| {
        let bytes = include_bytes!("fixtures/regex-reference.json.gz");
        assert_eq!(
            format!("{:x}", Sha256::digest(bytes)),
            "a6d503b427c339717c31b6754551c155fcf2ef2783ba91cc72f9c5fe7d1c7d1b"
        );
        #[derive(Deserialize)]
        struct Corpus {
            cases: Vec<RegexCase>,
        }
        #[derive(Deserialize)]
        struct RegexCase {
            name: String,
            text: String,
            pattern: String,
            tree: Option<Value>,
            repr: Option<String>,
            error: Option<ParseError>,
        }
        let mut text = String::new();
        GzDecoder::new(&bytes[..])
            .read_to_string(&mut text)
            .unwrap();
        let corpus: Corpus = serde_json::from_str(&text).unwrap();
        assert_eq!(corpus.cases.len(), 890);
        let mut errors = vec![];
        for c in corpus.cases {
            match (parse(&c.text, &c.name, ParseLimits::default()), c.error) {
                (Ok(got), None) => {
                    if let Some(diff) = difference(
                        &serde_json::to_value(&got).unwrap(),
                        c.tree.as_ref().unwrap(),
                        "",
                    ) {
                        errors.push(format!("{} {:?} AST {diff}", c.name, c.pattern));
                    } else if got.python_repr() != c.repr.unwrap() {
                        errors.push(format!("{} repr", c.name));
                    }
                }
                (Err(got), Some(want)) => {
                    if got != want {
                        errors.push(format!("{} {:?}: {got:?} != {want:?}", c.name, c.pattern));
                    }
                }
                (Ok(_), Some(want)) => {
                    errors.push(format!("{} {:?} expected {want:?}", c.name, c.pattern))
                }
                (Err(got), None) => {
                    errors.push(format!("{} {:?} unexpected {got:?}", c.name, c.pattern))
                }
            }
        }
        assert!(
            errors.is_empty(),
            "{} regex mismatches:\n{}",
            errors.len(),
            errors
                .iter()
                .take(40)
                .cloned()
                .collect::<Vec<_>>()
                .join("\n")
        );
    })
}
#[test]
fn flat_else_when_and_else_if_chains_stop_with_resource_diagnostics() {
    let when = format!(
        "language \"kql/2\";module chains;query q{{{}{{}}select 1;}}",
        "when true {} else ".repeat(2000)
    );
    let conditional = format!(
        "language \"kql/2\";module chains;pattern P(){{body{{{}{{}}}}}}",
        "if(true){}else ".repeat(2000)
    );
    for text in [when, conditional] {
        let error = parse(&text, "chains", ParseLimits::default()).unwrap_err();
        assert_eq!(error.code, "resource_limit");
        assert!(error.span.end <= text.len());
    }
}

#[test]
fn nested_blocks_and_expressions_have_bounded_default_stack_errors() {
    let texts = [
        format!(
            "language \"kql/2\";module nested;query q{{{}select 1;{}}}",
            "when true {".repeat(2000),
            "}".repeat(2000)
        ),
        format!(
            "language \"kql/2\";module nested;pattern P(){{body{{{}{}}}}}",
            "if(true){".repeat(2000),
            "}".repeat(2000)
        ),
        format!(
            "language \"kql/2\";module nested;query q{{select {}1{};}}",
            "(".repeat(2000),
            ")".repeat(2000)
        ),
    ];
    for text in texts {
        let err = parse(&text, "nested", ParseLimits::default()).unwrap_err();
        assert_eq!(err.code, "resource_limit");
        assert!(err.span.end <= text.len());
    }
}

#[test]
fn preparation_bounds_cross_declaration_expansion_and_external_ast_depth() {
    let mut text = String::from("language \"kql/2\";module long;");
    for i in 0..1000 {
        text.push_str(&format!("pattern P{i}(){{use P{}();}}", i + 1));
    }
    text.push_str("pattern P1000(){}query q{use P0();select 1;}");
    let tree = parse(&text, "long", ParseLimits::default()).unwrap();
    let error = ken_query::expand_indexed_alternatives(&tree, None).unwrap_err();
    assert_eq!(error.code, "resource_limit");
    assert_eq!(error.message, "alternative nesting limit exceeded");
    // Public typed records can be assembled without the parser; the preparation
    // boundary counts the actual topology, not cached expression depths.
    let mut tree = parse(
        "language \"kql/2\";module external;query q{select 1;}",
        "external",
        ParseLimits::default(),
    )
    .unwrap();
    let mut clause = tree.declarations[0].clauses[0].clone();
    for _ in 0..520 {
        let mut parent = tree.declarations[0].clauses[0].clone();
        parent.blocks = vec![vec![clause]];
        clause = parent;
    }
    tree.declarations[0].clauses = vec![clause];
    assert_eq!(
        resolve_libraries(&tree, &BTreeMap::new()).unwrap_err().code,
        "resource_limit"
    );
    assert_eq!(specialize_models(&tree).unwrap_err().code, "resource_limit");
    assert_eq!(
        ken_query::expand_indexed_alternatives(&tree, None)
            .unwrap_err()
            .code,
        "resource_limit"
    );
}
