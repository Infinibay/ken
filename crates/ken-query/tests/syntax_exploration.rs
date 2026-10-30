//! Pure syntax execution contract; records are deliberately independent of any graph.
use ken_query::exploration::{NodeRecord, SyntaxExecutionOptions, SyntaxPlan, SyntaxUnit, execute};
use ken_query::{BackendPreference, ParseLimits, Program, execution::Cancellation};
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::Arc, time::Instant};
fn program(body: &str, projection: &str) -> Program {
    let source =
        format!("language \"kql/2\"; module syntax_test; query q {{{body} select {projection};}}");
    let tree = ken_query::parse(&source, "<query>", ParseLimits::default()).unwrap();
    ken_query::compile(&tree, None, &BTreeMap::new(), BackendPreference::Automatic)
        .unwrap()
        .program
}
#[expect(
    clippy::too_many_arguments,
    reason = "Fixture columns mirror the raw syntax record schema"
)]
fn node(
    native: &str,
    kind: &str,
    category: &str,
    parent: Option<usize>,
    end: usize,
    start_byte: usize,
    end_byte: usize,
    role: &str,
    flags: u8,
) -> NodeRecord {
    NodeRecord {
        native_kind: native.into(),
        kind: kind.into(),
        category: category.into(),
        parent,
        subtree_end: end,
        start_byte,
        end_byte,
        role: role.into(),
        flags,
    }
}
fn unit() -> Arc<SyntaxUnit> {
    Arc::new(
        SyntaxUnit::new(
            "a.py".into(),
            "python".into(),
            Arc::<[u8]>::from(&b"if x: pass\nif y: pass\n"[..]),
            vec![
                node("module", "module", "declaration", None, 11, 0, 22, "", 1),
                node("if_statement", "if", "statement", Some(0), 6, 0, 10, "", 1),
                node("if", "if", "opaque", Some(1), 3, 0, 2, "", 0),
                node(
                    "identifier",
                    "identifier",
                    "expression",
                    Some(1),
                    4,
                    3,
                    4,
                    "condition",
                    1,
                ),
                node(
                    "block",
                    "block",
                    "statement",
                    Some(1),
                    6,
                    6,
                    10,
                    "consequence",
                    1,
                ),
                node(
                    "pass_statement",
                    "pass",
                    "statement",
                    Some(4),
                    6,
                    6,
                    10,
                    "",
                    1,
                ),
                node(
                    "if_statement",
                    "if",
                    "statement",
                    Some(0),
                    11,
                    11,
                    21,
                    "",
                    1,
                ),
                node("if", "if", "opaque", Some(6), 8, 11, 13, "", 0),
                node(
                    "identifier",
                    "identifier",
                    "expression",
                    Some(6),
                    9,
                    14,
                    15,
                    "condition",
                    1,
                ),
                node(
                    "block",
                    "block",
                    "statement",
                    Some(6),
                    11,
                    17,
                    21,
                    "consequence",
                    1,
                ),
                node(
                    "pass_statement",
                    "pass",
                    "statement",
                    Some(9),
                    11,
                    17,
                    21,
                    "",
                    1,
                ),
            ],
        )
        .unwrap(),
    )
}
fn run(
    body: &str,
    projection: &str,
    coverage: bool,
    options: SyntaxExecutionOptions,
) -> ken_query::exploration::SyntaxOutcome {
    let plan = SyntaxPlan::compile(&program(body, projection)).unwrap();
    execute(&plan, &[unit()], coverage, options).unwrap()
}
fn rows(outcome: &ken_query::exploration::SyntaxOutcome) -> Value {
    serde_json::to_value(&outcome.rows).unwrap()
}
#[test]
fn raw_preorder_is_validated_before_it_becomes_an_immutable_unit() {
    for records in [
        vec![node(
            "module",
            "module",
            "declaration",
            None,
            2,
            0,
            1,
            "",
            1,
        )],
        vec![
            node("module", "module", "declaration", None, 2, 0, 1, "", 1),
            node(
                "identifier",
                "identifier",
                "expression",
                Some(1),
                2,
                0,
                1,
                "",
                1,
            ),
        ],
        vec![
            node("module", "module", "declaration", None, 2, 0, 1, "", 1),
            node(
                "identifier",
                "identifier",
                "expression",
                Some(0),
                2,
                0,
                2,
                "",
                1,
            ),
        ],
    ] {
        assert!(
            SyntaxUnit::new(
                "a.py".into(),
                "python".into(),
                Arc::<[u8]>::from(&b"x"[..]),
                records
            )
            .is_err()
        );
    }
}
#[test]
fn optimized_and_reference_scan_agree_but_report_their_actual_physical_work() {
    let fast = run(
        "node $n {kind:\"if\";}",
        "$n.line,$n.path",
        true,
        Default::default(),
    );
    let slow = run(
        "node $n {kind:\"if\";}",
        "$n.line,$n.path",
        true,
        SyntaxExecutionOptions {
            reference: true,
            ..Default::default()
        },
    );
    assert_eq!(rows(&fast), json!([[1, "a.py"], [2, "a.py"]]));
    assert_eq!(rows(&fast), rows(&slow));
    assert!(fast.complete && slow.complete);
    assert_eq!(fast.scanned_nodes, 2);
    assert!(slow.scanned_nodes > fast.scanned_nodes);
}
#[test]
fn nested_scans_use_immediate_raw_children_and_never_mix_units() {
    let got = run(
        "node $n {kind:\"if\";node $c {kind:\"identifier\";role:\"condition\";}}",
        "$n.line,$c.name,$c.text",
        true,
        Default::default(),
    );
    assert_eq!(rows(&got), json!([[1, "x", "x"], [2, "y", "y"]]));
    let got = run(
        "node $n {kind:\"if\";} node $p {kind:\"pass\";} where contains_direct($n,$p);",
        "$n.line",
        true,
        Default::default(),
    );
    assert_eq!(rows(&got), json!([]));
}
#[test]
fn finite_domains_preserve_distinct_node_identity_and_closed_subtrees() {
    assert_eq!(
        rows(&run(
            "",
            "count(CodeNode $n | $n.kind == \"if\" | $n),exists(CodeNode $n | $n.kind == \"while\"),forall(CodeNode $n | $n.kind == \"if\" | $n.line > 0)",
            true,
            Default::default()
        )),
        json!([[2, false, true]])
    );
    let unknown = run(
        "not exists {node $n {kind:\"while\";}}",
        "1",
        false,
        Default::default(),
    );
    assert_eq!(rows(&unknown), json!([]));
    assert_eq!(unknown.unknown_candidates, 1);
    let closed = run(
        "node $n {kind:\"if\";} not exists {node $c {kind:\"call\";} where contains($n,$c);}",
        "$n.line",
        false,
        Default::default(),
    );
    assert_eq!(rows(&closed), json!([[1], [2]]));
    assert_eq!(closed.unknown_candidates, 0);
}
#[test]
fn unknown_properties_nested_in_values_cannot_prove_absence() {
    for reference in [false, true] {
        let out = run(
            "",
            "not exists(CodeNode $n | $n.kind == \"identifier\" and [$n.type_kind] == [\"str\"])",
            true,
            SyntaxExecutionOptions {
                reference,
                ..Default::default()
            },
        );
        assert_eq!(rows(&out), json!([]));
        assert_eq!(out.unknown_candidates, 1);
    }
}
#[test]
fn expression_errors_are_barriers_to_scan_and_quantifier_prefilters() {
    for reference in [false, true] {
        for (body, projection) in [
            ("bind $a = 1 / 0; where false;", "$a"),
            (
                "node $n {kind:\"if\";} node $r {kind:\"pass\";} bind $a = 1 / 0; where contains($r,$n);",
                "$a",
            ),
            (
                "",
                "exists(CodeNode $n | 1 / 0 == 0.0 and $n.kind == \"return\")",
            ),
        ] {
            let out = run(
                body,
                projection,
                true,
                SyntaxExecutionOptions {
                    reference,
                    ..Default::default()
                },
            );
            assert!(!out.complete);
            assert!(out.reason.unwrap().contains("division by zero"));
        }
    }
    assert!(
        run(
            "where false; bind $a = 1 / 0;",
            "$a",
            true,
            Default::default()
        )
        .complete
    );
}
#[test]
fn cancellation_deadlines_and_result_budgets_are_visible() {
    let cancellation = Cancellation::default();
    cancellation.cancel();
    let out = run(
        "node $n {kind:\"if\";}",
        "$n.line",
        true,
        SyntaxExecutionOptions {
            cancellation,
            ..Default::default()
        },
    );
    assert!(!out.complete);
    assert_eq!(out.reason.as_deref(), Some("cancelled"));
    for (options, reason) in [
        (
            SyntaxExecutionOptions {
                deadline: Some(Instant::now()),
                ..Default::default()
            },
            "timeout",
        ),
        (
            SyntaxExecutionOptions {
                max_states: Some(1),
                ..Default::default()
            },
            "max_states",
        ),
        (
            SyntaxExecutionOptions {
                max_rows: Some(1),
                ..Default::default()
            },
            "max_rows",
        ),
    ] {
        let out = run("node $n {kind:\"if\";}", "$n.line", true, options);
        assert!(!out.complete);
        assert_eq!(out.reason.as_deref(), Some(reason));
    }
}
#[test]
fn union_distinct_order_limit_regex_and_lossless_scalars_use_the_shared_value_owner() {
    let tree=ken_query::parse(r#"language "kql/2"; module t; query q {{bind $x=2;} or {bind $x=2;} or {bind $x=1;} select $x; order by $x asc; limit 1;}"#,"<query>",ParseLimits::default()).unwrap();
    let program = ken_query::compile(&tree, None, &BTreeMap::new(), BackendPreference::Automatic)
        .unwrap()
        .program;
    let out = execute(
        &SyntaxPlan::compile(&program).unwrap(),
        &[],
        true,
        Default::default(),
    )
    .unwrap();
    assert_eq!(rows(&out), json!([[1]]));
    assert!(out.results_truncated);
    let out = run(
        "node $n {native_kind:/^if_statement$/;}",
        "$n.line",
        true,
        Default::default(),
    );
    assert_eq!(rows(&out), json!([[1], [2]]));
    let out = run(
        "",
        "123456789012345678901234567890,\"\\ud800\"",
        true,
        Default::default(),
    );
    let encoded = serde_json::to_string(&out.rows).unwrap();
    assert!(encoded.contains("123456789012345678901234567890"));
    assert!(encoded.contains("\\ud800"));
}
#[test]
fn unsupported_semantics_are_admission_errors_not_empty_answers() {
    for body in [
        "callable $n {}",
        "node $n {namespace:\"x\";}",
        "node $n {} node $m {} where same_symbol($n,$m);",
    ] {
        assert!(SyntaxPlan::compile(&program(body, "1")).is_err());
    }
}

#[test]
fn compile_only_explanation_shares_legacy_syntax_admission_with_execution() {
    for body in ["callable $n {}", "node $n {namespace:\"x\";}"] {
        let mut program = program(body, "1");
        program.steps.clear();
        let compiled = ken_query::CompiledQuery {
            program,
            relational: None,
        };
        assert!(ken_query::authoring::explain(&compiled, "exploration").is_err());
    }
}
