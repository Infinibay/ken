//! Ordinary memory commands preserve their CLI presentation over native domains.
use clap::Parser;
use ken_cli::memory::MemoryCommand;
use serde_json::{Value, json};
use std::{
    path::Path,
    process::{Command, Output},
};
#[derive(Parser)]
struct Tree {
    #[command(subcommand)]
    command: MemoryCommand,
}
fn args(values: &[&str]) -> MemoryCommand {
    Tree::try_parse_from(std::iter::once("ken-rs").chain(values.iter().copied()))
        .unwrap()
        .command
}
fn fixture() -> tempfile::TempDir {
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir(root.path().join(".ken")).unwrap();
    std::fs::write(root.path().join(".ken/meta.json"), "{}").unwrap();
    let mut db = ken_store::ProjectDatabase::open(&root.path().join(".ken/ken.db")).unwrap();
    db.initialize().unwrap();
    root
}
fn run(root: &Path, values: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_ken-rs"))
        .arg("--resources")
        .arg(root.join("deliberately-missing-resources.json"))
        .args(values)
        .current_dir(root)
        .env_clear()
        .env("HOME", root)
        .env("KEN_CONFIG_DIR", root.join("config"))
        .env("PATH", "")
        .env("KEN_EMBED_DEVICE", "cpu")
        .output()
        .unwrap()
}
fn value(output: Output) -> Value {
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}
#[test]
fn ordinary_command_defaults_and_kind_choices_remain_distinct_from_consolidated_tools() {
    assert!(matches!(
        args(&[
            "remember",
            "topic",
            "content",
            "--tag",
            "one",
            "--tag",
            "two",
            "--kind",
            "persistent_rule"
        ]),
        MemoryCommand::Remember { .. }
    ));
    assert!(matches!(
        args(&["findings"]),
        MemoryCommand::Findings { limit: 20, .. }
    ));
    assert!(matches!(
        args(&["recall", "find", "the", "store"]),
        MemoryCommand::Recall {
            limit: 5,
            min_score: 0.25,
            ..
        }
    ));
    assert!(matches!(
        args(&["related-findings", "topic"]),
        MemoryCommand::RelatedFindings {
            limit: 8,
            min_weight: 0.3,
            ..
        }
    ));
    assert!(matches!(
        args(&["file-findings", "src/a.rs", "--expand"]),
        MemoryCommand::FileFindings {
            limit: 15,
            expand: true,
            ..
        }
    ));
    assert!(
        Tree::try_parse_from([
            "ken-rs", "remember", "topic", "content", "--kind", "invented"
        ])
        .is_err()
    );
    assert!(Tree::try_parse_from(["ken-rs", "recall"]).is_err());
    assert!(Tree::try_parse_from(["ken-rs", "findings-graph"]).is_err());
}
#[test]
fn save_list_and_forget_are_native_durable_and_model_failure_does_not_lose_content() {
    let root = fixture();
    let saved = run(
        root.path(),
        &[
            "remember",
            " durable ",
            " persisted 🦀 ",
            "--tag",
            "audit",
            "--tag",
            "kind:hypothesis",
            "--tag",
            "type:finding",
            "--kind",
            "persistent_rule",
        ],
    );
    assert!(
        saved.status.success(),
        "{}",
        String::from_utf8_lossy(&saved.stderr)
    );
    assert_eq!(
        String::from_utf8(saved.stdout).unwrap(),
        "remembered: durable\n"
    );
    let listed = value(run(root.path(), &["findings", "--json"]));
    assert_eq!(listed[0]["topic"], "durable");
    assert_eq!(listed[0]["content"], "persisted 🦀");
    assert_eq!(listed[0]["type"], "persistent_rule");
    assert_eq!(listed[0]["tags"], json!(["audit", "kind:persistent_rule"]));
    let db = rusqlite::Connection::open(root.path().join(".ken/ken.db")).unwrap();
    assert!(
        db.query_row("SELECT embedding FROM cr_findings", [], |r| r
            .get::<_, Option<Vec<u8>>>(0))
            .unwrap()
            .is_none()
    );
    drop(db);
    let text = run(root.path(), &["findings"]);
    assert!(text.status.success());
    let text = String::from_utf8(text.stdout).unwrap();
    assert!(text.contains("0.000  durable"));
    assert!(text.contains("persisted 🦀"));
    let deleted = run(root.path(), &["forget", "durable"]);
    assert!(deleted.status.success());
    assert_eq!(
        String::from_utf8(deleted.stdout).unwrap(),
        "forgot: durable\n"
    );
    let missing = run(root.path(), &["forget", "durable"]);
    assert_eq!(missing.status.code(), Some(1));
    assert_eq!(
        String::from_utf8(missing.stderr).unwrap(),
        "not found: durable\n"
    );
    assert_eq!(value(run(root.path(), &["findings", "--json"])), json!([]));
    assert!(!root.path().join("models-private").exists());
    assert!(!root.path().join("models-cache").exists());
}
#[test]
fn json_domain_rejections_and_missing_projects_keep_original_exit_and_stream_contracts() {
    let root = fixture();
    let invalid = run(root.path(), &["remember", "", "note", "--json"]);
    assert_eq!(invalid.status.code(), Some(1));
    let response: Value = serde_json::from_slice(&invalid.stdout).unwrap();
    assert_eq!(response["ok"], false);
    assert!(invalid.stderr.is_empty());
    let missing = run(root.path(), &["forget", "unknown", "--json"]);
    assert_eq!(missing.status.code(), Some(1));
    let response: Value = serde_json::from_slice(&missing.stdout).unwrap();
    assert_eq!(response["deleted"], 0);
    assert!(missing.stderr.is_empty());
    let other = tempfile::tempdir().unwrap();
    let missing = run(other.path(), &["findings", "--json"]);
    assert_eq!(missing.status.code(), Some(1));
    assert!(missing.stdout.is_empty());
    assert!(String::from_utf8_lossy(&missing.stderr).contains("error: no .ken project"));
    assert!(!other.path().join(".ken").exists());
}
#[test]
fn graph_and_exact_topic_operations_remain_cold_and_present_original_empty_notes() {
    let root = fixture();
    value(run(
        root.path(),
        &["remember", "exact-topic", "local source note", "--json"],
    ));
    let related = run(root.path(), &["related-findings", "exact-topic"]);
    assert!(
        related.status.success(),
        "{}",
        String::from_utf8_lossy(&related.stderr)
    );
    assert!(String::from_utf8_lossy(&related.stdout).contains("no related findings"));
    let file = run(root.path(), &["file-findings", "missing.rs", "--expand"]);
    assert!(file.status.success());
    assert_eq!(
        String::from_utf8(file.stdout).unwrap(),
        "no findings reference this file\n"
    );
    let rebuilt = value(run(root.path(), &["findings-graph", "rebuild", "--json"]));
    assert_eq!(rebuilt["ok"], true);
    assert_eq!(rebuilt["edges"], 0);
    assert_eq!(rebuilt["refs"], 0);
    let rebuilt = run(root.path(), &["findings-graph", "rebuild"]);
    assert!(rebuilt.status.success());
    assert_eq!(
        String::from_utf8(rebuilt.stdout).unwrap(),
        "findings graph rebuilt: 0 refs, 0 edges\n"
    );
}
#[test]
fn list_limit_precedes_exact_tag_filter_and_subdirectory_project_discovery_works() {
    let root = fixture();
    value(run(
        root.path(),
        &["remember", "earlier", "first", "--tag", "audit", "--json"],
    ));
    value(run(
        root.path(),
        &["remember", "later", "second", "--tag", "other", "--json"],
    ));
    assert_eq!(
        value(run(
            root.path(),
            &["findings", "-n", "1", "--tag", "audit", "--json"]
        )),
        json!([])
    );
    assert_eq!(
        value(run(
            root.path(),
            &["findings", "-n", "2", "--tag", "audit", "--json"]
        ))[0]["topic"],
        "earlier"
    );
    std::fs::create_dir(root.path().join("child")).unwrap();
    let output = run(&root.path().join("child"), &["findings", "--json"]);
    let rows = value(output);
    assert_eq!(rows.as_array().unwrap().len(), 2);
}
#[test]
fn nonempty_semantic_query_reaches_focused_resource_owner_and_errors_are_actionable() {
    let root = fixture();
    let output = run(
        root.path(),
        &[
            "recall",
            "find",
            "persisted",
            "notes",
            "--min-score",
            "0.4",
            "--json",
        ],
    );
    assert_eq!(output.status.code(), Some(1));
    assert!(
        String::from_utf8_lossy(&output.stderr).contains("deliberately-missing-resources.json")
    );
    assert!(!root.path().join("models-private").exists());
    assert!(!root.path().join("models-cache").exists());
}
