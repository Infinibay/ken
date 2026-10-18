use ken_cli::{args::parse_from, status::render};
use ken_core::status::StatusReport;
use serde_json::{Value, json};
use std::{
    ffi::OsString,
    fs,
    path::Path,
    process::{Command, Output},
};
use tempfile::TempDir;

fn project() -> TempDir {
    let t = TempDir::new().unwrap();
    fs::create_dir(t.path().join(".ken")).unwrap();
    fs::write(
        t.path().join(".ken/meta.json"),
        r#"{"project_id":{"name":"fixture"},"auth_token":"fixture-secret"}"#,
    )
    .unwrap();
    t
}
fn invoke(root: &Path, args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_ken-rs"))
        .args(args)
        .current_dir(root)
        .env_remove("KEN_PROJECT_ROOT")
        .env("HOME", root.join("empty-home"))
        .output()
        .unwrap()
}
fn database(root: &Path) {
    let c = rusqlite::Connection::open(root.join(".ken/ken.db")).unwrap();
    c.execute_batch(include_str!("../../../src/ken/schema.sql"))
        .unwrap();
    c.execute(
        "INSERT INTO ci_files(path,content_hash,mtime,indexed_at) VALUES('live.py',x'00',1,1)",
        [],
    )
    .unwrap();
    fs::write(root.join("live.py"), "code").unwrap();
}
#[test]
fn metadata_only_and_missing_project_have_correct_streams() {
    let out = render(
        &StatusReport::MissingProject {
            error: "no ken project found at or above /fixture".into(),
        },
        true,
    )
    .unwrap();
    assert_eq!(out.code, 1);
    assert!(out.stderr.is_empty());
    assert_eq!(
        serde_json::from_str::<Value>(&out.stdout).unwrap(),
        json!({"ok":false,"error":"no ken project found at or above /fixture"})
    );
    let missing = TempDir::new().unwrap();
    let out = invoke(missing.path(), &["status"]);
    assert_eq!(out.status.code(), Some(1));
    assert!(out.stdout.is_empty());
    assert_eq!(
        String::from_utf8(out.stderr).unwrap(),
        format!(
            "no ken project found at or above {}\nhint: `ken install .` from a project root\n",
            missing.path().canonicalize().unwrap().display()
        )
    );
    let t = project();
    let out = invoke(t.path(), &["status"]);
    assert!(out.status.success());
    assert!(out.stderr.is_empty());
    assert_eq!(
        String::from_utf8(out.stdout).unwrap(),
        format!(
            "project_root  : {}\n(no DB yet — run `ken install .`)\n",
            t.path().canonicalize().unwrap().display()
        )
    );
    assert!(!t.path().join(".ken/ken.db").exists());
}
#[test]
fn installed_text_omits_inventory_json_keeps_it() {
    let t = project();
    database(t.path());
    let text = invoke(t.path(), &["status"]);
    assert!(text.status.success());
    assert!(text.stderr.is_empty());
    assert_eq!(
        String::from_utf8(text.stdout).unwrap(),
        format!(
            "project_root  : {}\nfiles indexed : 1 (0 embedded)\nsymbols       : 0 (0 embedded)\nembedding cov : 0/1 (0.0%)\nrecommendation: run `ken rank \"your task\"` once to lazily build embeddings\ndaemon        : stopped\n",
            t.path().canonicalize().unwrap().display()
        )
    );
    let out = invoke(t.path(), &["status", ".", "--json"]);
    assert!(out.status.success());
    let report: Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(report["counts"].as_object().unwrap().len(), 15);
    assert_eq!(report["counts"]["sessions"], 0);
    assert_eq!(report["recommendations"].as_array().unwrap().len(), 4);
}
#[test]
fn argument_errors_exit_two() {
    let t = project();
    for args in [
        vec!["status", "--unknown"],
        vec!["status", ".", "extra"],
        vec!["install"],
    ] {
        let out = invoke(t.path(), &args);
        assert_eq!(out.status.code(), Some(2));
        assert!(out.stdout.is_empty());
        assert!(!out.stderr.is_empty());
    }
    let help = invoke(t.path(), &["--help"]);
    assert!(help.status.success());
    assert!(help.stderr.is_empty());
    let help = String::from_utf8(help.stdout).unwrap();
    assert!(help.contains("status"));
    assert!(!help.contains("install"));
    let version = invoke(t.path(), &["--version"]);
    assert!(version.status.success());
    assert_eq!(version.stdout, b"ken-rs 0.18.0\n");
    let parsed = parse_from(
        ["ken-rs", "status", "--json", "."]
            .into_iter()
            .map(OsString::from),
    )
    .unwrap();
    assert!(parsed.json);
    assert_eq!(parsed.path, Path::new("."));
    let child = t.path().join("-project");
    fs::create_dir_all(child.join(".ken")).unwrap();
    fs::copy(
        t.path().join(".ken/meta.json"),
        child.join(".ken/meta.json"),
    )
    .unwrap();
    let out = invoke(t.path(), &["status", "--json", "--", "-project"]);
    assert!(out.status.success());
    assert_eq!(
        serde_json::from_slice::<Value>(&out.stdout).unwrap()["project_root"],
        child.canonicalize().unwrap().to_str().unwrap()
    );
}
#[test]
fn json_preserves_types_and_all_keys() {
    let t = project();
    database(t.path());
    for args in [vec!["status", "--json", "."], vec!["status", ".", "--json"]] {
        let out = invoke(t.path(), &args);
        assert!(out.status.success());
        assert!(out.stderr.is_empty());
        let report: Value = serde_json::from_slice(&out.stdout).unwrap();
        assert_eq!(report["project_id"], json!({"name":"fixture"}));
        assert_eq!(report["ok"], true);
        assert_eq!(report["installed"], true);
        assert_eq!(report.as_object().unwrap().len(), 11);
        assert!(report["embedding_coverage"]["percent"].is_f64());
        assert!(
            report["counts"]
                .as_object()
                .unwrap()
                .values()
                .all(Value::is_u64)
        );
        assert!(
            !String::from_utf8(out.stdout)
                .unwrap()
                .contains("fixture-secret")
        );
    }
}
#[test]
fn corrupt_input_has_no_success_stdout() {
    let t = project();
    for content in ["{", "[]", r#"{"auth_token":"fixture-secret"}"#] {
        fs::write(t.path().join(".ken/meta.json"), content).unwrap();
        let out = invoke(t.path(), &["status", "--json"]);
        assert_eq!(out.status.code(), Some(1));
        assert!(out.stdout.is_empty());
        let err = String::from_utf8(out.stderr).unwrap();
        assert!(err.starts_with("ken-rs status:"));
        assert!(!err.contains("fixture-secret"));
    }
    fs::write(t.path().join(".ken/meta.json"), r#"{"project_id":null}"#).unwrap();
    fs::write(t.path().join(".ken/ken.db"), "broken").unwrap();
    let out = invoke(t.path(), &["status", "--json"]);
    assert_eq!(out.status.code(), Some(1));
    assert!(out.stdout.is_empty());
    assert!(
        String::from_utf8(out.stderr)
            .unwrap()
            .starts_with("ken-rs status:")
    );
}
