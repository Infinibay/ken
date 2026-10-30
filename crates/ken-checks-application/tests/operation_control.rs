//! Operation cancellation applies before entering a worker, not just inside it.
use ken_checks_application::{ChecksApplication, Resources, WorkerControl, WorkerProgram};
use ken_contracts::checks::{Receipt, Store};
use serde_json::{Value, json};
use std::{
    path::{Path, PathBuf},
    time::{Duration, Instant},
};
fn app(root: &Path) -> ChecksApplication {
    let grammar =
        PathBuf::from(std::env::var_os("KEN_GRAMMAR_MANIFEST").expect("prepared native grammar"));
    ChecksApplication::new(
        root,
        Resources::prepared(
            &grammar,
            WorkerProgram::new(root.join("worker-must-not-start")),
        )
        .unwrap(),
    )
    .unwrap()
}
fn definition() -> Value {
    json!({"id":"control.create","description":"Canceled admission must not publish","path":".","expectation":"some_match","query":"language \"kql/2\";module operation_control;query q{select 1;}"})
}
fn assert_no_rules(root: &Path) {
    assert!(Store::new(root).unwrap().rules().unwrap().is_empty());
    assert!(!root.join(".ken/checks/runs").exists());
}
#[test]
fn precanceled_create_returns_cancellation_without_saving_a_rule() {
    let root = tempfile::tempdir().unwrap();
    let app = app(root.path());
    let control = WorkerControl::default();
    control.cancellation.cancel();
    let result = app.manage_with_control(
        &json!({"action":"create","definition":definition()}),
        &control,
    );
    assert!(
        result.is_err(),
        "pre-canceled creation must not return a saved draft"
    );
    assert!(result.err().unwrap().to_string().contains("cancel"));
    assert_no_rules(root.path());
}
#[test]
fn expired_create_cannot_hash_compile_or_publish_success() {
    let root = tempfile::tempdir().unwrap();
    let app = app(root.path());
    let control = WorkerControl {
        deadline: Some(Instant::now() - Duration::from_secs(1)),
        ..Default::default()
    };
    let result = app.manage_with_control(
        &json!({"action":"create","definition":definition()}),
        &control,
    );
    assert!(
        result.is_err(),
        "an expired operation must not create a rule before a worker is invoked"
    );
    assert!(result.err().unwrap().to_string().contains("timeout"));
    assert_no_rules(root.path());
}
#[test]
fn canceled_empty_check_does_not_certify_not_applicable() {
    let root = tempfile::tempdir().unwrap();
    let app = app(root.path());
    let control = WorkerControl::default();
    control.cancellation.cancel();
    let result = app.check_with_control(&json!({}), &control);
    assert!(
        result.is_err(),
        "canceled empty selection must not return not_applicable success"
    );
    assert!(result.err().unwrap().to_string().contains("cancel"));
    assert_no_rules(root.path());
}
#[test]
fn zero_freshness_budget_rejects_before_engine_identity_even_for_an_empty_receipt() {
    let root = tempfile::tempdir().unwrap();
    let app = app(root.path());
    let receipt=Receipt::from_json(&json!({"version":1,"run_id":"control-empty","created_at":"2026-10-30T00:00:00Z","scope":"all","selection":"explicit","status":"not_applicable","checks":[]})).unwrap();
    Store::new(root.path())
        .unwrap()
        .write_receipt(&receipt)
        .unwrap();
    let result = app.freshness("control-empty", Duration::ZERO);
    assert!(
        result.is_err(),
        "zero freshness budget must not run full identity hash and return success"
    );
    assert!(result.err().unwrap().to_string().contains("timeout"));
}
