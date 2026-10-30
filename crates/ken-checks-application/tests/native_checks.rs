use ken_checks_application::{ChecksApplication, Resources, WorkerControl, WorkerProgram};
use ken_contracts::checks::{QueryRequest, judgment_observation};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    time::{Duration, Instant},
};
const GOOD: &str = "def emit():\n return 42\ndef wrap():\n return emit()\n";
const BAD: &str = "def emit():\n return 42\ndef wrap():\n emit()\n return 0\n";
const QUERY: &str = r#"language "kql/2";module checks_application;query q{callable $owner{name:"wrap";body{let $value=call $emit{name:"emit";};return $value;}}select $owner;}"#;
fn application(root: &Path) -> ChecksApplication {
    let worker = PathBuf::from(env!("CARGO_BIN_EXE_ken-check-worker"));
    let grammar = PathBuf::from(
        std::env::var_os("KEN_GRAMMAR_MANIFEST").expect("explicit prepared native grammars"),
    );
    ChecksApplication::new(
        root,
        Resources::prepared(&grammar, WorkerProgram::new(worker)).unwrap(),
    )
    .unwrap()
}
fn definition() -> Value {
    json!({"id":"application.return-witness","description":"Wrapper returns exact emission result","path":"src","expectation":"some_match","query":QUERY,"examples":[{"name":"returned","expect":"pass","files":{"src/a.py":GOOD}},{"name":"discarded","expect":"fail","files":{"src/a.py":BAD}}]})
}
fn source(root: &Path, value: &str) {
    std::fs::create_dir_all(root.join("src")).unwrap();
    std::fs::write(root.join("src/a.py"), value).unwrap();
}
#[test]
fn real_native_worker_validates_checks_regression_resolution_and_history() {
    let root = tempfile::tempdir().unwrap();
    source(root.path(), GOOD);
    let app = application(root.path());
    assert_eq!(
        app.check(&json!({})).unwrap().to_json().unwrap()["status"],
        "not_applicable"
    );
    app.manage(&json!({"action":"create","definition":definition()}))
        .unwrap();
    assert!(
        app.manage(&json!({"action":"enable","rule_id":"application.return-witness"}))
            .is_err()
    );
    assert_eq!(
        app.manage(&json!({"action":"validate","rule_id":"application.return-witness"}))
            .unwrap()["state"],
        "validated"
    );
    app.manage(&json!({"action":"enable","rule_id":"application.return-witness","automatic":true}))
        .unwrap();
    let before = app.check(&json!({"full":true})).unwrap().to_json().unwrap();
    assert_eq!(before["status"], "pass");
    let id = before["run_id"].as_str().unwrap();
    assert_eq!(
        app.freshness(id, Duration::from_secs(2)).unwrap()["state"],
        "unchanged"
    );
    source(root.path(), BAD);
    let failed = app
        .check(&json!({"compare":id}))
        .unwrap()
        .to_json()
        .unwrap();
    assert_eq!(failed["status"], "fail");
    assert_eq!(failed["comparison"]["changes"][0]["change"], "regression");
    source(root.path(), GOOD);
    let fixed = app
        .check(&json!({"compare":failed["run_id"]}))
        .unwrap()
        .to_json()
        .unwrap();
    assert_eq!(fixed["comparison"]["changes"][0]["change"], "resolved");
    assert_eq!(
        app.check(&json!({"run_id":id,"full":true}))
            .unwrap()
            .to_json()
            .unwrap(),
        before
    );
    let reopened = application(root.path());
    assert_eq!(
        reopened.check(&json!({})).unwrap().to_json().unwrap()["status"],
        "pass"
    );
}
fn query_request(root: &Path, source: String) -> QueryRequest {
    QueryRequest {
        root: root.into(),
        source,
        query_name: None,
        libraries: BTreeMap::new(),
        path: "src".into(),
        source_paths: None,
        timeout_ms: Some(10000.),
        max_states: Some(200000),
        max_rows: Some(100),
        source_profile: "full".into(),
    }
}
#[test]
fn valid_surrogate_and_large_integer_query_rows_survive_process_and_receipt() {
    let root = tempfile::tempdir().unwrap();
    source(root.path(), GOOD);
    let app = application(root.path());
    let number = "7".repeat(500);
    let query =
        format!(r#"language "kql/2";module lossless_check;query q{{select {number},"\ud800";}}"#);
    let observed = app
        .observe(
            &query_request(root.path(), query.clone()),
            &WorkerControl::default(),
        )
        .unwrap();
    assert_eq!(
        judgment_observation(&observed, "some_match"),
        "pass",
        "observation: {}",
        serde_json::to_string(&observed).unwrap()
    );
    assert!(observed.to_json().is_err());
    let text = serde_json::to_string(&observed).unwrap();
    assert!(text.contains(&number) && text.contains("\\ud800"));
    let mut rule = definition();
    rule["query"] = json!(query);
    app.manage(&json!({"action":"create","definition":rule}))
        .unwrap();
    let receipt = app
        .check(&json!({"rules":["application.return-witness"],"full":true}))
        .unwrap();
    assert!(receipt.to_json().is_err());
    assert!(receipt.json().contains(&number) && receipt.json().contains("\\ud800"));
    let compact = app
        .check(&json!({"rules":["application.return-witness"]}))
        .unwrap();
    assert!(compact.json().contains("\\ud800"));
}
#[test]
fn worker_timeout_and_inherited_cancellation_cannot_become_empty_success() {
    let root = tempfile::tempdir().unwrap();
    source(root.path(), GOOD);
    let app = application(root.path());
    let mut request = query_request(root.path(), QUERY.into());
    request.timeout_ms = Some(1.);
    let start = Instant::now();
    let result = app.observe(&request, &WorkerControl::default()).unwrap();
    assert_eq!(judgment_observation(&result, "some_match"), "unknown");
    assert_eq!(result.to_json().unwrap()["reason"], "timeout");
    assert!(start.elapsed() < Duration::from_secs(2));
    let control = WorkerControl::default();
    control.cancellation.cancel();
    request.timeout_ms = Some(10000.);
    let result = app.observe(&request, &control).unwrap();
    assert_eq!(result.to_json().unwrap()["reason"], "cancelled");
    assert_eq!(judgment_observation(&result, "no_matches"), "unknown");
    let control = WorkerControl {
        deadline: Some(Instant::now()),
        ..Default::default()
    };
    assert_eq!(
        app.observe(&request, &control).unwrap().to_json().unwrap()["reason"],
        "timeout"
    );
    assert_eq!(
        judgment_observation(
            &app.observe(&request, &WorkerControl::default()).unwrap(),
            "some_match"
        ),
        "pass"
    );
}
#[test]
fn source_scope_dependencies_pinned_modules_and_analyzed_code_are_respected() {
    let root = tempfile::tempdir().unwrap();
    source(root.path(), GOOD);
    std::fs::write(root.path().join("src/other.py"), "x=1\n").unwrap();
    std::fs::create_dir(root.path().join("ken")).unwrap();
    let marker = root.path().join("source-was-executed");
    let malicious = format!(
        "from pathlib import Path\nPath({:?}).touch()\nraise RuntimeError('project module executed')\n",
        marker.to_string_lossy()
    );
    std::fs::write(root.path().join("ken/__init__.py"), &malicious).unwrap();
    std::fs::write(root.path().join("sitecustomize.py"), &malicious).unwrap();
    let app = application(root.path());
    app.manage(&json!({"action":"create","definition":definition()}))
        .unwrap();
    let report = app
        .check(&json!({"rules":["application.return-witness"],"path":"src/other.py","full":true}))
        .unwrap()
        .to_json()
        .unwrap();
    assert_eq!(report["status"], "pass");
    assert_eq!(report["checks"][0]["path"], "src");
    assert!(!marker.exists());
    std::fs::write(
        root.path().join("src/a.py"),
        format!("from support import emit\n{GOOD}"),
    )
    .unwrap();
    std::fs::write(root.path().join("support.py"), "def emit(): return 42\n").unwrap();
    let report = app
        .check(&json!({"rules":["application.return-witness"],"full":true}))
        .unwrap()
        .to_json()
        .unwrap();
    let id = report["run_id"].as_str().unwrap();
    std::fs::write(root.path().join("support.py"), "def emit(): return 99\n").unwrap();
    assert_eq!(
        app.freshness(id, Duration::from_secs(2)).unwrap()["state"],
        "stale"
    );
}
#[test]
fn registered_rule_imports_remain_pinned_until_explicit_update() {
    let root = tempfile::tempdir().unwrap();
    source(root.path(), "class WitnessClass: pass\n");
    let registry = ken_structural::application::modules::ModuleRegistry::new(root.path()).unwrap();
    let library = r#"language "kql/2";module project.contract_fragment;pattern Pick(out TypeDecl $c){class $c{name:"WitnessClass";}}"#;
    let saved = registry.save(library, None, None).unwrap();
    let query = r#"language "kql/2";module pinned_rule;import project.contract_fragment;query q{use project.contract_fragment.Pick(c:$c);select $c.name;}"#;
    let mut rule = definition();
    rule["query"] = json!(query);
    let app = application(root.path());
    app.manage(&json!({"action":"create","definition":rule}))
        .unwrap();
    let stored = app
        .manage(&json!({"action":"show","rule_id":"application.return-witness","full":true}))
        .unwrap();
    assert_eq!(
        stored["definition"]["libraries"]["project.contract_fragment"],
        library
    );
    registry
        .save(
            &library.replace("WitnessClass", "OtherClass"),
            None,
            Some(&saved.revision),
        )
        .unwrap();
    assert_eq!(
        app.check(&json!({"rules":["application.return-witness"]}))
            .unwrap()
            .to_json()
            .unwrap()["status"],
        "pass"
    );
    app.manage(
        &json!({"action":"update","rule_id":"application.return-witness","definition":rule}),
    )
    .unwrap();
    assert_eq!(
        app.check(&json!({"rules":["application.return-witness"]}))
            .unwrap()
            .to_json()
            .unwrap()["status"],
        "fail"
    );
}
#[test]
fn read_only_lifecycle_does_not_require_worker_but_execution_is_unknown_if_missing() {
    let root = tempfile::tempdir().unwrap();
    source(root.path(), GOOD);
    let grammar = PathBuf::from(std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap());
    let missing = root.path().join("not-installed/ken-check-worker");
    let app = ChecksApplication::new(
        root.path(),
        Resources::prepared(&grammar, WorkerProgram::new(missing)).unwrap(),
    )
    .unwrap();
    assert!(
        app.manage(&json!({"action":"list"})).unwrap()["rules"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    assert!(
        app.related("src/a.py", 10).unwrap().to_json().unwrap()["rules"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    app.manage(&json!({"action":"create","definition":definition()}))
        .unwrap();
    let result = app
        .check(&json!({"rules":["application.return-witness"]}))
        .unwrap()
        .to_json()
        .unwrap();
    assert_eq!(result["status"], "unknown");
    assert!(
        result["checks"][0]["reason"]
            .as_str()
            .is_some_and(|s| !s.is_empty())
    );
}
#[test]
fn native_batch_shares_total_budget_and_preserves_opaque_rows_and_source_receipt() {
    let root = tempfile::tempdir().unwrap();
    source(root.path(), GOOD);
    std::fs::write(root.path().join("src/b.py"), "class Unrelated: pass\n").unwrap();
    let app = application(root.path());
    let mut request = query_request(root.path(), QUERY.into());
    request.source_paths = Some(vec!["src/a.py".into()]);
    let second = r#"language "kql/2";module batch_literal;query q{select "\udfff";}"#.to_owned();
    let queries = BTreeMap::from([("first".into(), QUERY.into()), ("second".into(), second)]);
    let batch = app
        .observe_batch(&request, &queries, None, false, &WorkerControl::default())
        .unwrap();
    assert_eq!(batch.results.len(), 2);
    for result in batch.results.values() {
        assert_eq!(result.row_count(), Some(1));
        assert_eq!(judgment_observation(result, "some_match"), "pass");
        assert!(
            result.metadata("check_snapshot").unwrap().unwrap()["manifest"]
                .as_array()
                .unwrap()
                .len()
                >= 2
        );
    }
    assert!(batch.to_json().is_err());
    assert!(serde_json::to_string(&batch).unwrap().contains("\\udfff"));
    request.timeout_ms = Some(1.);
    let timed = app
        .observe_batch(&request, &queries, None, false, &WorkerControl::default())
        .unwrap();
    assert!(
        timed
            .results
            .values()
            .all(|r| judgment_observation(r, "some_match") == "unknown")
    );
}
