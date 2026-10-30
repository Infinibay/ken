use flate2::read::GzDecoder;
use ken_query::{ParseError, PythonRepr, ast::File, compile_relational};
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
    has_graph: Option<bool>,
    program: Option<Box<RawValue>>,
    plan: Option<Value>,
    repr: Option<String>,
    error: Option<ParseError>,
    unexpected: Option<Value>,
}
fn decode<T: for<'de> Deserialize<'de>>(s: &str) -> T {
    let mut d = serde_json::Deserializer::from_str(s);
    d.disable_recursion_limit();
    T::deserialize(&mut d).unwrap()
}
fn difference(a: &Value, b: &Value, p: &str) -> String {
    if let (Some(a), Some(b)) = (a.as_object(), b.as_object()) {
        for (k, v) in a {
            if b.get(k) != Some(v) {
                return b.get(k).map_or_else(
                    || format!("{p}/{k} missing"),
                    |b| difference(v, b, &format!("{p}/{k}")),
                );
            }
        }
    }
    if let (Some(a), Some(b)) = (a.as_array(), b.as_array()) {
        if a.len() != b.len() {
            return format!("{p} len{} !={}", a.len(), b.len());
        }
        for (i, (a, b)) in a.iter().zip(b).enumerate() {
            if a != b {
                return difference(a, b, &format!("{p}/{i}"));
            }
        }
    }
    format!("{p}: {a} != {b}")
}
#[test]
fn relational_plans_literals_dispatch_and_diagnostics_match_original() {
    std::thread::Builder::new()
        .stack_size(64 * 1024 * 1024)
        .spawn(|| {
            assert_eq!(
                format!(
                    "{:x}",
                    Sha256::digest(include_bytes!("../resources/relational-capabilities.json"))
                ),
                "b0d3a69e5e8eca927b034c704a5e916c7e9d5079ea5e008fbb8d42f18e262dc4"
            );
            let bytes = include_bytes!("fixtures/relational-reference.json.gz");
            assert_eq!(bytes.len(), 121358);
            assert_eq!(
                format!("{:x}", Sha256::digest(bytes)),
                "c0899f8f0cab01ec1393935d3de70e85cd2fcac02ce5895f0a463b9fc1137d34"
            );
            let mut s = String::new();
            GzDecoder::new(&bytes[..]).read_to_string(&mut s).unwrap();
            let f: Corpus = decode(&s);
            assert_eq!(f.cases.len(), 440);
            let mut errors = vec![];
            for c in f.cases {
                let tree: File = decode(c.tree.get());
                if let Some(expected) = c.has_graph {
                    let got = ken_query::relational::has_graph(&tree, None);
                    if got != expected {
                        errors.push(format!("{} dispatch {got} !={expected}", c.name));
                    }
                }
                let result = compile_relational(&tree, None);
                if c.unexpected.is_some() {
                    if result.is_ok() {
                        errors.push(format!("{} original host failure accepted", c.name));
                    }
                    continue;
                }
                match (result, c.error) {
                    (Ok(p), None) => {
                        let got = serde_json::to_value(&p.program).unwrap();
                        let want: Value = decode(c.program.as_ref().unwrap().get());
                        if got != want {
                            errors.push(format!(
                                "{} program {}",
                                c.name,
                                difference(&got, &want, "")
                            ));
                        } else if p.program.python_repr() != c.repr.unwrap() {
                            errors.push(format!("{} repr", c.name));
                        }
                        let got = serde_json::to_value(p.relational.unwrap()).unwrap();
                        if Some(&got) != c.plan.as_ref() {
                            errors.push(format!(
                                "{} plan {}",
                                c.name,
                                difference(&got, c.plan.as_ref().unwrap(), "")
                            ));
                        }
                    }
                    (Err(got), Some(want)) => {
                        if got != want {
                            errors.push(format!("{}: {got:?} !={want:?}", c.name));
                        }
                    }
                    (Err(got), None) => errors.push(format!("{} unexpected {got:?}", c.name)),
                    (Ok(_), Some(e)) => errors.push(format!("{} succeeded vs{e:?}", c.name)),
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
fn explicit_snapshot_compilation_and_depth_boundary_match_original() {
    #[derive(Deserialize)]
    struct CoordinatorCase {
        name: String,
        tree: Box<RawValue>,
        libraries: std::collections::BTreeMap<String, Box<RawValue>>,
        force: bool,
        program: Option<Box<RawValue>>,
        repr: Option<String>,
        relational: Option<bool>,
        plan: Option<Value>,
        error: Option<ParseError>,
    }
    #[derive(Deserialize)]
    struct CoordinatorCorpus {
        cases: Vec<CoordinatorCase>,
    }
    std::thread::Builder::new()
        .stack_size(64 * 1024 * 1024)
        .spawn(|| {
            let bytes = include_bytes!("fixtures/compilation-reference.json.gz");
            assert_eq!(bytes.len(), 30544);
            assert_eq!(
                format!("{:x}", Sha256::digest(bytes)),
                "76f73dfcee0101816a76a4404b0661ec3439e364ed644bd5754a7bbb20a7aac8"
            );
            let mut s = String::new();
            GzDecoder::new(&bytes[..]).read_to_string(&mut s).unwrap();
            let corpus: CoordinatorCorpus = decode(&s);
            assert_eq!(corpus.cases.len(), 34);
            for c in corpus.cases {
                let tree: File = decode(c.tree.get());
                let libraries = c
                    .libraries
                    .into_iter()
                    .map(|(k, v)| (k, decode::<File>(v.get())))
                    .collect();
                let result = ken_query::compile(
                    &tree,
                    None,
                    &libraries,
                    if c.force {
                        ken_query::BackendPreference::Relational
                    } else {
                        ken_query::BackendPreference::Automatic
                    },
                );
                match (result, c.error) {
                    (Ok(p), None) => {
                        let want: Value = decode(c.program.as_ref().unwrap().get());
                        assert_eq!(
                            serde_json::to_value(&p.program).unwrap(),
                            want,
                            "{}",
                            c.name
                        );
                        assert_eq!(p.program.python_repr(), c.repr.unwrap(), "{} repr", c.name);
                        assert_eq!(
                            p.relational.is_some(),
                            c.relational.unwrap(),
                            "{} backend",
                            c.name
                        );
                        if let Some(plan) = p.relational {
                            assert_eq!(
                                serde_json::to_value(plan).unwrap(),
                                c.plan.unwrap(),
                                "{} plan",
                                c.name
                            );
                        }
                    }
                    (Err(got), Some(want)) => assert_eq!(got, want, "{}", c.name),
                    (got, want) => panic!("{}: {got:?} vs{want:?}", c.name),
                }
            }
        })
        .unwrap()
        .join()
        .unwrap();
}

fn parse(text: &str) -> File {
    ken_query::parse(text, "native-relational", ken_query::ParseLimits::default()).unwrap()
}
#[test]
fn alias_rewriting_preserves_literal_tokens_and_input_snapshots() {
    use ken_query::relational::{PlanValue, Term};
    let tree = parse(
        "language \"kql/2\";module identity;query q{edge ENTITY($base,\"CLASS\"){name:\"$alias.foo\";};bind $alias=$base;edge HAS_METHOD($alias,\"$base.x\");select $alias;}",
    );
    let before = serde_json::to_string(&tree).unwrap();
    let result = compile_relational(&tree, None).unwrap();
    let plan = result.relational.unwrap();
    assert_eq!(plan.exports.get("alias").unwrap(), "$base");
    assert_eq!(plan.nodes.len(), 2);
    let PlanValue::Edge(first) = &plan.nodes[0].value else {
        panic!("fact")
    };
    assert_eq!(first.attrs[0].2, "$alias.foo");
    let PlanValue::Edge(second) = &plan.nodes[1].value else {
        panic!("fact")
    };
    assert_eq!(second.subject, Term::Text("$base".into()));
    assert_eq!(second.object.literal(), Some("$base.x"));
    assert_eq!(second.object.token(), "\"$base.x\"");
    assert_eq!(serde_json::to_string(&tree).unwrap(), before);
}
#[test]
fn shared_patterns_and_forwarded_nodes_have_one_immutable_cached_plan() {
    use std::sync::Arc;
    let tree = parse(
        "language \"kql/2\";module shared;pattern P(out GraphTerm $x){edge ENTITY($x,\"CLASS\");}query q{use P(x:$a);use P(x:$b);select $a,$b;}",
    );
    let result = compile_relational(&tree, None).unwrap();
    let plan = result.relational.unwrap();
    assert_eq!(plan.definitions.items().len(), 1);
    let deps = plan.dependencies();
    assert_eq!(deps.len(), 2);
    assert_eq!(deps[0].0, deps[1].0);
    assert_eq!(deps[0].1.get("x").unwrap(), "$a");
    assert_eq!(deps[1].1.get("x").unwrap(), "$b");
    let tree = parse(
        "language \"kql/2\";module shared;pattern P(out GraphTerm $x){edge ENTITY($x,\"CLASS\");}query q{use P(x:$a);select $a;}",
    );
    let result = compile_relational(&tree, None).unwrap();
    let plan = result.relational.unwrap();
    let child = plan
        .definitions
        .get(&format!("{}:P", result.program.fingerprint))
        .unwrap();
    assert!(Arc::ptr_eq(&plan.nodes, &child.nodes));
    assert!(plan.dependencies().is_empty());
    assert_eq!(plan.definitions.items().len(), 2);
}
#[test]
fn private_roles_and_wide_exports_keep_scope_and_order() {
    let tree = parse(
        "language \"kql/2\";module private;query q{optional{class $private{}}select $private;}",
    );
    assert_eq!(
        compile_relational(&tree, None).unwrap_err().message,
        "graph output is not bound in every alternative"
    );
    let mut text =
        String::from("language \"kql/2\";module columns;query q{edge ENTITY($x,\"CLASS\");select ");
    for i in 0..4000 {
        if i > 0 {
            text.push(',');
        }
        text.push_str(&format!("$x as c{i}"));
    }
    text.push_str(";}");
    let result = compile_relational(&parse(&text), None).unwrap();
    let plan = result.relational.unwrap();
    assert_eq!(plan.exports.items().len(), 4000);
    assert_eq!(plan.exports.items()[0].0, "c0");
    assert_eq!(plan.exports.items()[3999].0, "c3999");
    assert_eq!(plan.exports.get("c1729").unwrap(), "$x");
}
#[test]
fn corrupt_graph_records_are_controlled_and_cross_declaration_depth_is_bounded() {
    use ken_query::ast::Expression;
    let source = parse(
        "language \"kql/2\";module bad;query q{edge ENTITY($x,\"CLASS\"){name:/ok/;};select $x;}",
    );
    for bad in ["", "é/", "/x/zz", "/x/ii"] {
        let mut tree = source.clone();
        if let Expression::Query(e) =
            &mut tree.declarations[0].clauses[0].blocks[0][0].expressions[0]
        {
            e.value = bad.into();
        }
        assert!(compile_relational(&tree, None).is_err());
    }
    let mut text = String::from("language \"kql/2\";module deep;");
    for i in 0..600 {
        text.push_str(&format!("pattern P{i}(){{use P{}();}}", i + 1));
    }
    text.push_str("pattern P600(){}query q{edge ENTITY($x,\"CLASS\");use P0();select $x;}");
    let error = compile_relational(&parse(&text), None).unwrap_err();
    assert_eq!(error.code, "resource_limit");
    assert_eq!(error.message, "relational pattern depth limit exceeded");
}
#[test]
fn wide_graph_work_and_shared_dependency_dags_are_bounded() {
    let text = format!(
        "language \"kql/2\";module work;query q{{{}select $x;}}",
        "edge TYPE($x,$x);".repeat(66000)
    );
    let error = compile_relational(&parse(&text), None).unwrap_err();
    assert_eq!(error.code, "resource_limit");
    let mut text = String::from("language \"kql/2\";module dag;");
    for i in 0..128 {
        text.push_str(&format!(
            "pattern P{i}(){{use P{}();use P{}();}}",
            i + 1,
            i + 1
        ));
    }
    text.push_str("pattern P128(){}query q{edge ENTITY($x,\"CLASS\");use P0();select $x;}");
    let p = compile_relational(&parse(&text), None)
        .unwrap()
        .relational
        .unwrap();
    assert_eq!(p.definitions.items().len(), 129);
}

#[test]
fn generated_semantic_witnesses_share_the_materialization_budget() {
    let text = format!(
        "language \"kql/2\";module generated;query q{{edge TYPE($a,$b);{}select $a;}}",
        "where preserves($a,$b);".repeat(2000)
    );
    let error = compile_relational(&parse(&text), None).unwrap_err();
    assert_eq!(error.code, "resource_limit");
}

#[test]
fn generated_witness_names_follow_each_block_bound_scope() {
    use ken_query::relational::{PlanValue, Term};
    for (before, suffix) in [("", "_"), ("where preserves($a,$b);", "__")] {
        let text = format!(
            "language \"kql/2\";module names;query q{{edge TYPE($a,$b);{before}either{{where preserves($a,$b);}}or{{where preserves($a,$b);}}where preserves($a,$b);select $a;}}"
        );
        let plan = compile_relational(&parse(&text), None)
            .unwrap()
            .relational
            .unwrap();
        let last = plan.nodes.last().unwrap();
        let PlanValue::Edge(edge) = &last.children[0][0].value else {
            panic!("witness fact")
        };
        assert_eq!(
            edge.object,
            Term::Text(format!("$preserved_return_return{suffix}"))
        );
    }
}

#[test]
fn retained_graph_payloads_are_budgeted_before_materialization() {
    use ken_query::ast::Expression;
    let base = parse("language \"kql/2\";module payload;query q{edge TYPE($x,$x);select $x;}");
    let mut tree = base.clone();
    let Expression::Query(projection) = &base.declarations[0].clauses[1].expressions[0] else {
        unreachable!()
    };
    tree.declarations[0].clauses[1].expressions = (0..66000)
        .map(|i| {
            let mut e = projection.clone();
            e.value = format!("c{i}");
            Expression::Query(e)
        })
        .collect();
    assert!(compile_relational(&tree, None).is_err_and(|e| e.code == "resource_limit"));
    let mut tree = base.clone();
    let mut list = projection.args[0].clone();
    list.kind = "list".into();
    list.value.clear();
    let mut literal = projection.args[0].clone();
    literal.kind = "literal".into();
    literal.value = "\"X\"".into();
    list.args = vec![literal; 66000];
    tree.declarations[0].clauses[0].expressions[1] = Expression::Query(list);
    assert!(compile_relational(&tree, None).is_err_and(|e| e.code == "resource_limit"));
}

#[test]
fn repeated_wide_scope_snapshots_share_the_work_budget() {
    for scope in ["either", "optional", "count"] {
        let mut text = String::from("language \"kql/2\";module snapshots;query q{");
        for i in 0..1000 {
            text.push_str(&format!("edge TYPE($x{i},$x{i});"));
        }
        text.push_str("select $x0;}");
        let mut tree = parse(&text);
        let mut branch =
            parse("language \"kql/2\";module b;query q{optional{edge TYPE($x0,$x0);}select $x0;}")
                .declarations
                .remove(0)
                .clauses
                .remove(0);
        branch.kind = scope.into();
        if scope == "either" {
            branch.blocks.push(branch.blocks[0].clone());
        }
        if scope == "count" {
            branch.role = "x0".into();
            branch.name = "==".into();
            branch.flags = vec!["1".into()];
        }
        tree.declarations[0]
            .clauses
            .splice(1000..1000, vec![branch; 100]);
        assert!(
            compile_relational(&tree, None).is_err_and(|e| e.code == "resource_limit"),
            "{scope}"
        );
    }
}

#[test]
fn string_regex_extensions_and_invalid_escapes_match_original() {
    let bytes = include_bytes!("fixtures/relational-regex-reference.json.gz");
    assert_eq!(bytes.len(), 1401);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "809ff9aba2443c7ce1ebe7fe7c6880e4eff10f3f31a57e832fc17ee75d70a72b"
    );
    assert_eq!(
        format!(
            "{:x}",
            Sha256::digest(include_bytes!("../resources/regex-properties.json"))
        ),
        "2320628a29037e51df72191258fe09e69ea2539c6198ce597030007eb40a48ef"
    );
    let mut s = String::new();
    GzDecoder::new(&bytes[..]).read_to_string(&mut s).unwrap();
    let corpus: Value = serde_json::from_str(&s).unwrap();
    let mut failures = vec![];
    for case in corpus["cases"].as_array().unwrap() {
        let pattern = case["pattern"].as_str().unwrap();
        let text = format!(
            "language \"kql/2\";module regex;query q{{edge TYPE($a,$b);where initialized_with($a,$b,name:{});select $a;}}",
            serde_json::to_string(pattern).unwrap()
        );
        let got = compile_relational(&parse(&text), None);
        if let Ok(compiled) = &got {
            let plan = compiled.relational.as_ref().unwrap();
            let ken_query::relational::PlanValue::Edge(edge) = &plan.nodes.last().unwrap().value
            else {
                panic!("initializer name fact")
            };
            assert_eq!(edge.attrs[0].2, pattern);
        }
        if got.is_ok() != case["valid"].as_bool().unwrap() {
            failures.push(format!("{pattern:?}: {got:?}"));
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[test]
fn string_regex_checking_bounds_nested_groups_sets_and_failed_name_scans() {
    for pattern in [
        format!("{}x{}", "(?:".repeat(600), ")".repeat(600)),
        format!("(?V1){}x{}", "[".repeat(600), "]".repeat(600)),
        "\\g<".repeat(10000),
    ] {
        let text = format!(
            "language \"kql/2\";module bounded;query q{{edge TYPE($a,$b);where initialized_with($a,$b,name:{});select $a;}}",
            serde_json::to_string(&pattern).unwrap()
        );
        assert!(compile_relational(&parse(&text), None).is_err_and(|e| e.code == "resource_limit"));
    }
}

#[test]
fn malformed_regex_limits_and_nested_duplicate_names_are_controlled() {
    for pattern in [
        "(?P<x>(?P<x>a)(?P=x))",
        "(a)(?+9223372036854775807)",
        "a{9223372036854775807<e<=9223372036854775807}",
        "a{999999999999999999999999,}",
    ] {
        let text = format!(
            "language \"kql/2\";module malformed;query q{{edge TYPE($a,$b);where initialized_with($a,$b,name:{});select $a;}}",
            serde_json::to_string(pattern).unwrap()
        );
        assert!(
            compile_relational(&parse(&text), None).is_err(),
            "{pattern}"
        );
    }
}
