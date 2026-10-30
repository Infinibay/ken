use flate2::read::GzDecoder;
use ken_query::{ParseError, PythonRepr, ast::File, compile_indexed};
use serde::Deserialize;
use serde_json::{Value, value::RawValue};
use sha2::{Digest, Sha256};
use std::io::Read;
#[derive(Deserialize)]
struct Corpus {
    cases: Vec<Case>,
}
#[derive(Deserialize)]
struct Case {
    name: String,
    tree: Box<RawValue>,
    program: Option<Box<RawValue>>,
    repr: Option<String>,
    error: Option<ParseError>,
    unexpected: Option<Value>,
}
fn decode<T: for<'de> Deserialize<'de>>(text: &str) -> T {
    let mut d = serde_json::Deserializer::from_str(text);
    d.disable_recursion_limit();
    T::deserialize(&mut d).unwrap()
}
#[test]
fn checked_indexed_programs_errors_and_fingerprints_match_original() {
    std::thread::Builder::new()
        .stack_size(64 * 1024 * 1024)
        .spawn(|| {
            let vocabulary = include_bytes!("../resources/capabilities.json");
            assert_eq!(vocabulary.len(), 8965);
            assert_eq!(
                format!("{:x}", Sha256::digest(vocabulary)),
                "743522d97fcfdba6c81aefda220954e9ec7330ac8e3ba4be8d2819728caff8ce"
            );
            let bytes = include_bytes!("fixtures/indexed-reference.json.gz");
            assert_eq!(bytes.len(), 179905);
            assert_eq!(
                format!("{:x}", Sha256::digest(bytes)),
                "e04f6384a3fe04d4791c2bd84005fe1f6529f851e2ec0eba84bd32a96b80fb12"
            );
            let mut text = String::new();
            GzDecoder::new(&bytes[..])
                .read_to_string(&mut text)
                .unwrap();
            let corpus: Corpus = decode(&text);
            assert_eq!(corpus.cases.len(), 534);
            let mut errors = vec![];
            for c in corpus.cases {
                let tree: File = decode(c.tree.get());
                let result = compile_indexed(&tree, None);
                if c.unexpected.is_some() {
                    if result.is_ok() {
                        errors.push(format!("{}: malformed AST accepted", c.name));
                    }
                    continue;
                }
                match (result, c.error) {
                    (Ok(got), None) => {
                        let value = serde_json::to_value(&got).unwrap();
                        let want: Value = decode(c.program.as_ref().unwrap().get());
                        if value != want {
                            let fields: Vec<_> = value
                                .as_object()
                                .unwrap()
                                .iter()
                                .filter(|(k, v)| want.get(k.as_str()) != Some(*v))
                                .map(|(k, _)| k.clone())
                                .collect();
                            errors.push(format!(
                                "{}: program fields {fields:?}; fingerprint {} != {}",
                                c.name, got.fingerprint, want["fingerprint"]
                            ));
                        } else if got.python_repr() != c.repr.unwrap() {
                            errors.push(format!("{}: repr differs", c.name));
                        }
                    }
                    (Err(got), Some(want)) => {
                        if got != want {
                            errors.push(format!("{}: {got:?} != {want:?}", c.name));
                        }
                    }
                    (Err(got), None) => errors.push(format!("{}: unexpected {got:?}", c.name)),
                    (Ok(_), Some(want)) => {
                        errors.push(format!("{}: succeeded vs {want:?}", c.name))
                    }
                }
            }
            assert!(
                errors.is_empty(),
                "{} mismatches:\n{}",
                errors.len(),
                errors
                    .iter()
                    .take(35)
                    .cloned()
                    .collect::<Vec<_>>()
                    .join("\n")
            );
        })
        .unwrap()
        .join()
        .unwrap();
}

#[test]
fn body_plans_captures_and_failure_side_effects_match_original() {
    use std::collections::BTreeMap;
    #[derive(Deserialize)]
    struct BodyCorpus {
        cases: Vec<BodyCase>,
    }
    #[derive(Deserialize)]
    struct BodyCase {
        name: String,
        clause: ken_query::ast::Clause,
        owner: String,
        mapping: BTreeMap<String, String>,
        roles: BTreeMap<String, String>,
        expected: BTreeMap<String, String>,
        roles_after: BTreeMap<String, String>,
        pattern: Option<Value>,
        repr: Option<String>,
        error: Option<ParseError>,
    }
    let bytes = include_bytes!("fixtures/body-check-reference.json.gz");
    assert_eq!(bytes.len(), 37959);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "be4698f3a09e7fdf7c3812a4dd75162a516ca25e500046f0358c13387b8846d4"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    let corpus: BodyCorpus = decode(&text);
    assert_eq!(corpus.cases.len(), 670);
    let mut errors = vec![];
    for c in corpus.cases {
        let mut roles = c.roles;
        let result = ken_query::compile_body(
            &c.clause,
            &c.owner,
            &c.mapping,
            &mut roles,
            Some(&c.expected),
        );
        match (result, c.error) {
            (Ok(p), None) => {
                if serde_json::to_value(&p).unwrap() != c.pattern.unwrap() {
                    errors.push(format!("{}: pattern differs", c.name));
                } else if p.python_repr() != c.repr.unwrap() {
                    errors.push(format!("{}: repr differs", c.name));
                }
            }
            (Err(got), Some(want)) => {
                if got != want {
                    errors.push(format!("{}: {got:?} != {want:?}", c.name));
                }
            }
            (Err(got), None) => errors.push(format!("{}: unexpected {got:?}", c.name)),
            (Ok(_), Some(want)) => errors.push(format!("{}: succeeded vs {want:?}", c.name)),
        }
        if roles != c.roles_after {
            errors.push(format!(
                "{}: roles {roles:?} != {:?}",
                c.name, c.roles_after
            ));
        }
    }
    assert!(
        errors.is_empty(),
        "{} mismatches:\n{}",
        errors.len(),
        errors
            .iter()
            .take(35)
            .cloned()
            .collect::<Vec<_>>()
            .join("\n")
    );
}

#[test]
fn native_compiler_rejects_broken_records_and_bounds_indirect_expansion() {
    use ken_query::{ParseLimits, compile_body, parse};
    use std::collections::BTreeMap;
    let parse = |s: &str| parse(s, "native", ParseLimits::default()).unwrap();
    let mut tree = parse("language \"kql/2\";module native;query q{class $c{}select $c;}");
    tree.declarations[0].clauses[0].blocks.clear();
    assert!(compile_indexed(&tree, None).is_err());
    let mut tree = parse("language \"kql/2\";module native;query q{select 1;limit 2;}");
    tree.declarations[0].clauses[1].name = "not-an-integer".into();
    assert!(compile_indexed(&tree, None).is_err());
    let mut tree = parse("language \"kql/2\";module native;query q{select 1;}");
    if let ken_query::ast::Expression::Query(e) =
        &mut tree.declarations[0].clauses[0].expressions[0]
    {
        e.args.clear();
    }
    assert!(compile_indexed(&tree, None).is_err());
    let base = parse("language \"kql/2\";module native;pattern P(){body{return 1;}}");
    let base = base.declarations[0].clauses[0].clone();
    let mut nested = base.clone();
    for _ in 0..520 {
        let mut parent = base.clone();
        parent.blocks = vec![vec![nested]];
        nested = parent;
    }
    let mut roles = BTreeMap::new();
    assert_eq!(
        compile_body(&nested, "owner", &BTreeMap::new(), &mut roles, None)
            .unwrap_err()
            .code,
        "resource_limit"
    );
    assert!(roles.is_empty());
    let mut text = String::from("language \"kql/2\";module native;");
    for i in 0..600 {
        text.push_str(&format!("pattern P{i}(){{use P{}();}}", i + 1));
    }
    text.push_str("pattern P600(){}query q{use P0();select 1;}");
    let tree = parse(&text);
    let err = compile_indexed(&tree, None).unwrap_err();
    assert_eq!(err.code, "resource_limit");
    assert_eq!(err.message, "pattern expansion depth limit exceeded");
    let mut text = String::from("language \"kql/2\";module native;");
    for i in 0..20 {
        text.push_str(&format!(
            "pattern P{i}(){{use P{}();use P{}();}}",
            i + 1,
            i + 1
        ));
    }
    text.push_str("pattern P20(){}query q{use P0();select 1;}");
    let err = compile_indexed(&parse(&text), None).unwrap_err();
    assert_eq!(err.code, "resource_limit");
    assert_eq!(err.message, "compilation work limit exceeded");
}
#[test]
fn indexed_branch_composition_preserves_global_limit_and_private_bindings() {
    use ken_query::{ParseLimits, compile_indexed_branches, parse};
    let tree=parse("language \"kql/2\";module branches;query q{either{class $x{}}or{interface $x{}}select $x;order by $x;limit 7;}","branches",ParseLimits::default()).unwrap();
    let untouched = serde_json::to_string(&tree).unwrap();
    let expanded = ken_query::expand_indexed_alternatives(&tree, None).unwrap();
    let original_plans: Vec<_> = expanded
        .iter()
        .map(|t| compile_indexed(t, None).unwrap())
        .collect();
    let p = compile_indexed_branches(&tree, None).unwrap();
    assert_eq!(p.limit.as_ref().unwrap().digits(), "7");
    assert_eq!(p.branches.len(), 2);
    assert!(p.branches.iter().all(|b| b.limit.is_none()));
    assert_eq!(
        p.branches
            .iter()
            .map(|b| b.fingerprint.as_str())
            .collect::<Vec<_>>(),
        original_plans
            .iter()
            .map(|b| b.fingerprint.as_str())
            .collect::<Vec<_>>()
    );
    let expected = format!(
        "{:x}",
        Sha256::digest(
            original_plans
                .iter()
                .map(|p| p.fingerprint.as_str())
                .collect::<String>()
                .as_bytes()
        )
    );
    assert_eq!(p.fingerprint, expected);
    assert_eq!(serde_json::to_string(&tree).unwrap(), untouched);
    let tree = parse(
        "language \"kql/2\";module branches;query q{either{class $x{}}or{class $y{}}select $x;}",
        "private",
        ParseLimits::default(),
    )
    .unwrap();
    assert!(compile_indexed_branches(&tree, None).is_err());
}

#[test]
fn wide_body_capture_order_and_resume_checks_use_default_stack() {
    use ken_query::{ParseLimits, compile_body, parse};
    use std::collections::BTreeMap;
    let mut text = String::from("language \"kql/2\";module wide;pattern P(){body{");
    for i in 0..10000 {
        text.push_str(&format!("call $f{{}}as $a{i};yield 1;resume next;"));
    }
    text.push_str("}}");
    let input = parse(&text, "wide", ParseLimits::default()).unwrap();
    let body = &input.declarations[0].clauses[0];
    let mut roles = BTreeMap::from([("f".into(), "callable".into())]);
    let plan = compile_body(body, "owner", &BTreeMap::new(), &mut roles, None).unwrap();
    assert_eq!(plan.outputs.len(), 10000);
    assert_eq!(plan.outputs.first().unwrap(), "a0");
    assert_eq!(plan.outputs.last().unwrap(), "a9999");
    assert_eq!(plan.clauses.len(), 30000);
    assert_eq!(roles.len(), 10001);
}

#[test]
fn construction_target_error_uses_the_outer_let_span() {
    use ken_query::{ParseLimits, compile_body, parse};
    use std::collections::BTreeMap;
    let tree = parse(
        "language \"kql/2\";module spans;pattern P(){body{let $v=construct $t{};}}",
        "span-case",
        ParseLimits::default(),
    )
    .unwrap();
    let body = &tree.declarations[0].clauses[0];
    let outer = &body.blocks[0][0];
    let mut roles = BTreeMap::from([("t".into(), "callable".into())]);
    let error = compile_body(body, "owner", &BTreeMap::new(), &mut roles, None).unwrap_err();
    assert_eq!(error.message, "construct requires a bound type");
    assert_eq!(error.span, outer.span);
}
#[test]
fn indexed_read_alias_remains_an_operation_even_when_expected_as_call() {
    use ken_query::{ParseLimits, compile_body, parse};
    use std::collections::BTreeMap;
    let tree = parse(
        "language \"kql/2\";module read;pattern P(){body{let $v=$p[0]as $read;}}",
        "read-case",
        ParseLimits::default(),
    )
    .unwrap();
    let mut roles = BTreeMap::from([("p".into(), "field".into())]);
    let expected = BTreeMap::from([("read".into(), "call".into())]);
    let plan = compile_body(
        &tree.declarations[0].clauses[0],
        "owner",
        &BTreeMap::new(),
        &mut roles,
        Some(&expected),
    )
    .unwrap();
    assert_eq!(roles["read"], "operation");
    assert_eq!(plan.outputs, ["v", "read"]);
    assert!(plan.call_aliases.is_empty());
}
#[test]
fn malformed_caller_built_name_regexes_return_diagnostics_without_panics() {
    use ken_query::{ParseLimits, ast::Expression, compile_body, parse};
    use std::collections::BTreeMap;
    let tree = parse(
        "language \"kql/2\";module regex;pattern P(){body{call $f{name:/ok/;};}}",
        "bad-regex",
        ParseLimits::default(),
    )
    .unwrap();
    let mut failures = vec![];
    for value in ["", "é/"] {
        let mut body = tree.declarations[0].clauses[0].clone();
        if let Expression::Query(e) = &mut body.blocks[0][0].blocks[0][0].expressions[0] {
            e.value = value.into();
        }
        let mut roles = BTreeMap::from([("f".into(), "callable".into())]);
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            compile_body(&body, "owner", &BTreeMap::new(), &mut roles, None)
        }));
        match result {
            Ok(Err(e)) => assert_eq!(e.code, "syntax_error"),
            _ => failures.push(value),
        }
    }
    assert!(
        failures.is_empty(),
        "invalid regex values accepted/panicked: {failures:?}"
    );
}

#[test]
fn wrapped_body_errors_preserve_original_span_and_domain_boundary() {
    use ken_query::{ParseLimits, parse};
    let tree=parse("language \"kql/2\";module wrapped;query q{callable $f{var $x{}body{let $v=construct $x{};}}select $f;}","wrapped",ParseLimits::default()).unwrap();
    let outer = &tree.declarations[0].clauses[0].blocks[0][1].blocks[0][0];
    let e = compile_indexed(&tree, None).unwrap_err();
    assert_eq!(e.code, "syntax_error");
    assert_eq!(e.span, outer.span);
    assert_eq!(
        e.message,
        format!(
            "wrapped:{}: construct requires a bound type",
            outer.span.start
        )
    );
    let tree=parse("language \"kql/2\";module wrapped;pattern P(in Callable $owner,out Call $read){callable $owner{var $container{}body{let $v=$container[0]as $read;}}}query q{callable $f{}use P(owner:$f,read:$read);select $f;}","wrapped",ParseLimits::default()).unwrap();
    let e = compile_indexed(&tree, None).unwrap_err();
    assert_eq!(e.code, "unsupported_capability");
    assert_eq!(e.message, "pattern parameter type does not match binding");
    assert_eq!(e.span, tree.declarations[1].clauses[1].span);
}
#[test]
fn oversized_pipeline_still_reports_later_lowering_errors_and_interval_precedence() {
    use ken_query::{ParseLimits, compile_body, parse};
    use std::collections::BTreeMap;
    let text = format!(
        "language \"kql/2\";module priority;query q{{{}use Missing();select 1;}}",
        "where true;".repeat(257)
    );
    let tree = parse(&text, "priority", ParseLimits::default()).unwrap();
    let e = compile_indexed(&tree, None).unwrap_err();
    assert_eq!(e.code, "unsupported_capability");
    assert_eq!(
        e.message,
        "unknown pattern or unsupported model/evidence argument"
    );
    let tree=parse("language \"kql/2\";module gap;pattern P(){body{call $f{};gap until next{forbid call($f);paths:bad;forbid call($f,through:indirect);}call $f{};}}","priority",ParseLimits::default()).unwrap();
    let mut roles = BTreeMap::from([("f".into(), "callable".into())]);
    let e = compile_body(
        &tree.declarations[0].clauses[0],
        "owner",
        &BTreeMap::new(),
        &mut roles,
        None,
    )
    .unwrap_err();
    assert_eq!(e.message, "forbid call currently requires through: direct");
}

#[test]
fn body_and_optional_expansion_share_the_lowering_work_budget() {
    use ken_query::{ParseLimits, parse};
    let sources = [
        format!(
            "language \"kql/2\";module work;pattern P(){{callable $c{{body{{{}}}}}}}query q{{{}select 1;}}",
            "call $f{};".repeat(128),
            "use P();".repeat(512)
        ),
        format!(
            "language \"kql/2\";module work;pattern P(){{{}}}query q{{{}select 1;}}",
            "optional{callable $c{}}".repeat(128),
            "use P();".repeat(256)
        ),
    ];
    for source in sources {
        let tree = parse(&source, "work", ParseLimits::default()).unwrap();
        let e = compile_indexed(&tree, None).unwrap_err();
        assert_eq!(e.code, "resource_limit");
        assert_eq!(e.message, "compilation work limit exceeded");
    }
}
