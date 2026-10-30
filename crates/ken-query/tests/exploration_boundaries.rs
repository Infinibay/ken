//! Admission and scheduling must use the same supported legacy program representation.
use ken_query::{
    BackendPreference, Program,
    exploration::{NodeRecord, SyntaxExecutionOptions, SyntaxPlan, SyntaxUnit, execute},
};
use serde_json::json;
use std::{collections::BTreeMap, sync::Arc};
fn program(body: &str, projection: &str) -> Program {
    let text =
        format!("language \"kql/2\";module boundaries;query q{{{body}select {projection};}}");
    let parsed = ken_query::parse(&text, "<query>", Default::default()).unwrap();
    ken_query::compile(
        &parsed,
        None,
        &BTreeMap::new(),
        BackendPreference::Automatic,
    )
    .unwrap()
    .program
}
fn unit() -> Arc<SyntaxUnit> {
    let row = |native: &str, kind: &str, parent, end| NodeRecord {
        native_kind: native.into(),
        kind: kind.into(),
        category: "syntax".into(),
        role: String::new(),
        parent,
        subtree_end: end,
        start_byte: 0,
        end_byte: 1,
        flags: 1,
    };
    Arc::new(
        SyntaxUnit::new(
            "one.py".into(),
            "python".into(),
            Arc::from(b"x".as_slice()),
            vec![
                row("module", "module", None, 3),
                row("if_statement", "if", Some(0), 3),
                row("pass_statement", "pass", Some(1), 3),
            ],
        )
        .unwrap(),
    )
}
#[test]
fn legacy_scan_fields_cannot_bypass_syntax_selector_or_property_admission() {
    for source in ["callable $n {}", "node $n {namespace:\"x\";}"] {
        let mut p = program(source, "1");
        p.steps.clear();
        assert!(
            SyntaxPlan::compile(&p).is_err(),
            "unsupported fallback was admitted: {source}"
        );
    }
}
#[test]
fn legacy_action_fields_keep_expression_errors_ahead_of_containment_prefilters() {
    let mut p = program(
        "node $n {kind:\"if\";}node $r {kind:\"pass\";}bind $a=1/0;where contains($r,$n);",
        "$a",
    );
    p.steps.clear();
    let plan = SyntaxPlan::compile(&p).unwrap();
    for reference in [false, true] {
        let outcome = execute(
            &plan,
            &[unit()],
            true,
            SyntaxExecutionOptions {
                reference,
                ..Default::default()
            },
        )
        .unwrap();
        assert!(!outcome.complete);
        assert!(outcome.reason.unwrap().contains("division by zero"));
    }
}
#[test]
fn wide_finite_quantifiers_preserve_node_domains_and_boolean_results() {
    let parameters = (0..64)
        .map(|i| format!("CodeNode $p{i}"))
        .collect::<Vec<_>>()
        .join(",");
    let p = program("", &format!("exists({parameters} | true)"));
    let plan = SyntaxPlan::compile(&p).unwrap();
    // One candidate per parameter keeps this a small finite execution, not a load test.
    let root = Arc::new(
        SyntaxUnit::new(
            "one.py".into(),
            "python".into(),
            Arc::from(b"x".as_slice()),
            vec![NodeRecord {
                native_kind: "module".into(),
                kind: "module".into(),
                category: "syntax".into(),
                role: String::new(),
                parent: None,
                subtree_end: 1,
                start_byte: 0,
                end_byte: 1,
                flags: 1,
            }],
        )
        .unwrap(),
    );
    let outcome = execute(&plan, &[root], true, Default::default()).unwrap();
    assert!(outcome.complete);
    assert_eq!(serde_json::to_value(outcome.rows).unwrap(), json!([[true]]));
}
