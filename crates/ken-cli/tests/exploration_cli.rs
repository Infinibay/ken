//! Backend flags select real source syntax / semantic bucket implementations.
use serde_json::{Value, json};
use std::{
    path::{Path, PathBuf},
    process::{Command, Output},
};
fn command(root: &Path, resources: &Path, args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_ken-rs"))
        .arg("--resources")
        .arg(resources)
        .args(args)
        .current_dir(root)
        .env_clear()
        .env("HOME", root)
        .env("PATH", "")
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
fn resources(root: &Path) -> PathBuf {
    let path = root.join("resources.json");
    std::fs::write(&path,json!({"format":"ken-search-installation/1","grammar_manifest":PathBuf::from(std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap())}).to_string()).unwrap();
    path
}
fn query_file(root: &Path) -> PathBuf {
    let p = root.join("query.kql");
    std::fs::write(
        &p,
        "language \"kql/2\";module exploration_cli;query q{node $n {kind:\"if\";}select $n.line;}",
    )
    .unwrap();
    p
}
#[test]
fn public_kql2_exploration_reports_true_syntax_capability_without_graph_persistence() {
    let d = tempfile::tempdir().unwrap();
    let r = resources(d.path());
    let q = query_file(d.path());
    std::fs::write(d.path().join("a.py"), "if x: pass\n").unwrap();
    let out = value(command(
        d.path(),
        &r,
        &[
            "kql2",
            q.to_str().unwrap(),
            "--backend",
            "exploration",
            "--cache-mb",
            "0",
            "--json",
            "--profile",
        ],
    ));
    assert_eq!(out["rows"], json!([[1]]));
    assert_eq!(out["capability"], "syntax-exploration/1");
    assert_eq!(out["analysis"]["backend"], "native_syntax_exploration");
    assert_eq!(out["analysis"]["semantic_resolution"], "not_requested");
    assert!(!d.path().join(".ken").exists());
}
#[test]
fn public_exploration_custom_cache_reuses_only_the_syntax_owner_and_sees_live_changes() {
    let d = tempfile::tempdir().unwrap();
    let cache = tempfile::tempdir().unwrap();
    let r = resources(d.path());
    let q = query_file(d.path());
    let p = d.path().join("a.py");
    std::fs::write(&p, "if x: pass\n").unwrap();
    let args = [
        "kql2",
        q.to_str().unwrap(),
        "--backend",
        "exploration",
        "--cache-directory",
        cache.path().to_str().unwrap(),
        "--cache-mb",
        "10",
        "--json",
    ];
    assert_eq!(
        value(command(d.path(), &r, &args))["analysis"]["parsed_units"],
        1
    );
    assert_eq!(
        value(command(d.path(), &r, &args))["analysis"]["reused_units"],
        1
    );
    std::fs::write(p, "x=1\nif y: pass\n").unwrap();
    assert_eq!(value(command(d.path(), &r, &args))["rows"], json!([[2]]));
    assert!(cache.path().join("syntax.sqlite").exists());
    assert!(!cache.path().join("source-cache.sqlite").exists());
    assert!(!d.path().join(".ken").exists());
}
#[test]
fn public_syntax_timeout_is_incomplete_exit_three_and_rejection_stays_cold() {
    let d = tempfile::tempdir().unwrap();
    let r = resources(d.path());
    let q = query_file(d.path());
    std::fs::write(d.path().join("a.py"), "if x: pass\n").unwrap();
    let stopped = command(
        d.path(),
        &r,
        &[
            "kql2",
            q.to_str().unwrap(),
            "--backend",
            "exploration",
            "--timeout-ms",
            "0",
            "--cache-mb",
            "0",
            "--json",
        ],
    );
    assert_eq!(stopped.status.code(), Some(3));
    let out: Value = serde_json::from_slice(&stopped.stdout).unwrap();
    assert_eq!(out["complete"], false);
    assert_eq!(out["reason"], "timeout");
    std::fs::write(
        &q,
        "language \"kql/2\";module unsupported;query q{callable $n {} select $n;}",
    )
    .unwrap();
    let bad = command(
        d.path(),
        &d.path().join("missing-resources"),
        &[
            "kql2",
            q.to_str().unwrap(),
            "--backend",
            "exploration",
            "--json",
        ],
    );
    assert_eq!(bad.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&bad.stderr).contains("selector"));
    assert!(!d.path().join(".ken").exists());
}
#[test]
fn public_patterns_honor_indexed_and_exploration_backend_profiles() {
    let d = tempfile::tempdir().unwrap();
    let r = resources(d.path());
    std::fs::write(
        d.path().join("Subject.java"),
        include_str!("../../ken-structural/tests/fixtures/exploration/singleton.java"),
    )
    .unwrap();
    for (backend, storage) in [("exploration", Some("native_buckets/1")), ("indexed", None)] {
        let out = value(command(
            d.path(),
            &r,
            &[
                "structural",
                "patterns",
                "--pattern",
                "singleton",
                "--backend",
                backend,
                "--profile",
                "--json",
                "--cache-mb",
                "0",
            ],
        ));
        assert_eq!(out["analysis"]["pattern_engine"]["backend"], backend);
        if let Some(storage) = storage {
            assert_eq!(out["analysis"]["pattern_engine"]["storage"], storage);
            assert!(
                out["analysis"]["pattern_engine"]["buckets"]["builds"]
                    .as_u64()
                    .unwrap()
                    > 0
            );
        } else {
            assert!(out["analysis"]["pattern_engine"]["buckets"].is_null());
        }
        assert_eq!(out["analysis"]["query_cache"]["hits"], 0);
    }
}
