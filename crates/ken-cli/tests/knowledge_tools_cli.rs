#[path = "../../ken-search/tests/support/navigation.rs"]
#[allow(dead_code)]
mod support;
use serde_json::{Value, json};
use std::process::Command;
use support::Fixture;
fn call(fixture: &Fixture, args: &[&str]) -> Value {
    let output = Command::new(env!("CARGO_BIN_EXE_ken-rs"))
        .arg("--resources")
        .arg(fixture.paths.root().join("unavailable.json"))
        .arg("tools")
        .arg("--path")
        .arg(fixture.paths.root())
        .arg("--json")
        .args(args)
        .env_clear()
        .env("HOME", fixture.paths.root())
        .env("PATH", "")
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}
#[test]
fn memory_public_tools_survive_optional_embedding_failure_and_recall_current_dependency_validity() {
    let fixture = Fixture::new();
    std::fs::write(
        fixture.paths.root().join("observed.txt"),
        "observed version\n",
    )
    .unwrap();
    let justification=json!({"kind":"observation","rationale":"Read the fixture source.","evidence":[{"path":"observed.txt"}],"assumptions":["fixture scope"],"recheck":"read observed.txt"}).to_string();
    let saved = call(
        &fixture,
        &[
            "remember",
            "native-proof",
            "--content",
            "The fixture owns this conclusion.",
            "--anchor-tool",
            "native-tool",
            "--justification",
            &justification,
        ],
    );
    assert_eq!(saved["ok"], true);
    let exact = call(
        &fixture,
        &["recall", "--topic", "native-proof", "--detail", "answer"],
    );
    assert_eq!(
        exact["memories"][0]["conclusion"],
        "The fixture owns this conclusion."
    );
    assert_eq!(exact["memories"][0]["validity"]["state"], "unchanged");
    let anchored = call(&fixture, &["ken_recall", "--anchor-tool", "native-tool"]);
    assert_eq!(anchored[0]["topic"], "native-proof");
    std::fs::write(fixture.paths.root().join("observed.txt"), "new version\n").unwrap();
    let stale = call(
        &fixture,
        &["recall", "--topic", "native-proof", "--detail", "answer"],
    );
    assert_eq!(stale["memories"][0]["validity"]["state"], "stale");
    assert_eq!(
        call(
            &fixture,
            &["remember", "native-proof", "--action", "forget"]
        )["ok"],
        true
    );
}
#[test]
fn reasoning_tools_persist_and_resume_across_native_cli_processes_without_models() {
    let fixture = Fixture::new();
    let facts = r#"[{"predicate":"owns","subject":"store","object":"writes"}]"#;
    assert_eq!(
        call(
            &fixture,
            &[
                "reason-record",
                "native-source",
                "--facts",
                facts,
                "--evidence",
                "current source"
            ]
        )["changed"],
        true
    );
    let goal = r#"{"predicate":"owns","subject":"store","object":"writes"}"#;
    let first = call(&fixture, &["reason", "Who owns writes?", "--goal", goal]);
    assert_eq!(first["status"], "supported");
    let resumed = call(
        &fixture,
        &["ken_reason", "Who owns writes?", "--goal", goal],
    );
    assert_eq!(resumed["status"], "supported");
    assert_eq!(resumed["reuse"]["checkpoint"], true);
    assert_eq!(resumed["reuse"]["new_work"], 0);
    call(&fixture, &["reason-record", "native-source", "--retract"]);
    let retracted = call(&fixture, &["reason", "Who owns writes?", "--goal", goal]);
    assert_ne!(retracted["status"], "supported");
}
