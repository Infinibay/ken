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
    let path = root.join(".fixture-resources.json");
    std::fs::write(&path,json!({"format":"ken-search-installation/1","grammar_manifest":PathBuf::from(std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap())}).to_string()).unwrap();
    path
}
#[test]
fn capabilities_and_compile_explanation_need_neither_project_nor_resource_manifest() {
    let root = tempfile::tempdir().unwrap();
    let missing = root.path().join("no-resources");
    let caps = value(command(
        root.path(),
        &missing,
        &["kql2", "--capabilities", "--json"],
    ));
    assert_eq!(caps["backends"]["indexed"]["body"], true);
    assert_eq!(caps["backends"]["exploration"]["body"], false);
    let query = root.path().join("query.kql");
    std::fs::write(
        &query,
        "language \"kql/2\";module authoring_cli;query q{node $a {} node $b {} select $a;}",
    )
    .unwrap();
    let explained = value(command(
        root.path(),
        &missing,
        &[
            "kql2",
            query.to_str().unwrap(),
            "--explain",
            "--backend",
            "exploration",
            "--root",
            "does-not-exist",
            "--json",
        ],
    ));
    assert_eq!(explained["executed"], false);
    assert_eq!(explained["diagnostics"][0]["code"], "disconnected_captures");
    assert!(!root.path().join(".ken").exists());
    assert!(!root.path().join("does-not-exist").exists());
}
#[test]
fn saved_queries_execute_live_sources_and_incomplete_queries_have_distinct_exit_status() {
    let root = tempfile::tempdir().unwrap();
    let manifest = resources(root.path());
    std::fs::write(
        root.path().join("code.py"),
        "class Alpha: pass\nclass Beta: pass\n",
    )
    .unwrap();
    let query = root.path().join("query.kql");
    std::fs::write(
        &query,
        "language \"kql/2\";module cli_saved;query q{class $c {} select $c.name;}",
    )
    .unwrap();
    let saved = value(command(
        root.path(),
        &root.path().join("missing"),
        &["kql2", query.to_str().unwrap(), "--save", "--json"],
    ));
    assert_eq!(saved["module"], "cli_saved");
    let result = value(command(
        root.path(),
        &manifest,
        &[
            "kql2",
            "--saved",
            "cli_saved",
            "--path",
            "code.py",
            "--cache-mb",
            "0",
            "--json",
        ],
    ));
    assert_eq!(result["rows"], json!([["Alpha"], ["Beta"]]));
    assert_eq!(result["complete"], true);
    let incomplete = command(
        root.path(),
        &manifest,
        &[
            "kql2",
            "--saved",
            "cli_saved",
            "--path",
            "code.py",
            "--cache-mb",
            "0",
            "--max-states",
            "1",
            "--json",
        ],
    );
    assert_eq!(incomplete.status.code(), Some(3));
    assert_eq!(
        serde_json::from_slice::<Value>(&incomplete.stdout).unwrap()["complete"],
        false
    );
}
#[test]
fn native_instruction_and_source_ir_views_use_current_captured_sources() {
    let root = tempfile::tempdir().unwrap();
    let manifest = resources(root.path());
    std::fs::write(
        root.path().join("code.py"),
        "def native(value):\n    result=value\n    return result\n",
    )
    .unwrap();
    let text = command(
        root.path(),
        &manifest,
        &[
            "structural",
            "ir",
            "--scope",
            "code.py",
            "--cache-mb",
            "0",
            "--view",
            "instructions",
            "--format",
            "text",
        ],
    );
    assert!(
        text.status.success(),
        "{}",
        String::from_utf8_lossy(&text.stderr)
    );
    let assembly = String::from_utf8(text.stdout).unwrap();
    assert!(assembly.contains("ken-instructions/1"));
    assert!(assembly.contains("func \"native\""));
    assert!(assembly.contains("slot.store"));
    let data = value(command(
        root.path(),
        &manifest,
        &[
            "structural",
            "ir",
            "--scope",
            "code.py",
            "--cache-mb",
            "0",
            "--view",
            "source",
            "--json",
        ],
    ));
    assert_eq!(data["ir"]["view"], "source");
    assert!(
        data["ir"]["entities"]
            .as_object()
            .unwrap()
            .values()
            .any(|e| e["name"] == "native")
    );
    std::fs::write(
        root.path().join("code.py"),
        "def updated(value): return value\n",
    )
    .unwrap();
    let data = value(command(
        root.path(),
        &manifest,
        &[
            "structural",
            "ir",
            "--scope",
            "code.py",
            "--cache-mb",
            "0",
            "--view",
            "instructions",
            "--json",
        ],
    ));
    assert_eq!(data["ir"]["functions"][0]["name"], "updated");
}
#[test]
fn structural_rule_library_lifecycle_is_cold_and_live_search_uses_its_shared_owner() {
    let root = tempfile::tempdir().unwrap();
    let manifest = resources(root.path());
    std::fs::write(root.path().join("code.py"), "class Native: pass\n").unwrap();
    let saved = value(command(
        root.path(),
        &root.path().join("missing"),
        &[
            "structural",
            "save-rule",
            "local.class",
            "--query",
            "require $x ENTITY CLASS",
            "--tag",
            "native",
            "--json",
        ],
    ));
    assert_eq!(saved["ok"], true);
    let listed = value(command(
        root.path(),
        &root.path().join("missing"),
        &["structural", "rules", "--rule", "local.class", "--json"],
    ));
    assert_eq!(listed["rules"].as_array().unwrap().len(), 1);
    let found = value(command(
        root.path(),
        &manifest,
        &[
            "structural",
            "search",
            "--rule",
            "local.class",
            "--scope",
            "code.py",
            "--cache-mb",
            "0",
            "--json",
        ],
    ));
    assert_eq!(found["matches"].as_array().unwrap().len(), 1);
}

#[test]
fn explicit_cache_directory_retains_native_queries_outside_the_project() {
    let root = tempfile::tempdir().unwrap();
    let external = tempfile::tempdir().unwrap();
    let manifest = resources(root.path());
    std::fs::write(root.path().join("code.py"), "class Cached: pass\n").unwrap();
    let query = root.path().join("query.kql");
    std::fs::write(
        &query,
        "language \"kql/2\";module cache_cli;query q{class $c {} select $c.name;}",
    )
    .unwrap();
    for _ in 0..2 {
        let found = value(command(
            root.path(),
            &manifest,
            &[
                "kql2",
                query.to_str().unwrap(),
                "--path",
                "code.py",
                "--cache-directory",
                external.path().to_str().unwrap(),
                "--cache-mb",
                "10",
                "--json",
            ],
        ));
        assert_eq!(found["rows"], json!([["Cached"]]));
        assert_eq!(found["complete"], true);
    }
    assert!(std::fs::read_dir(external.path()).unwrap().next().is_some());
    assert!(!root.path().join(".ken/structural").exists());
    assert!(!root.path().join(".ken/structural-cache.sqlite").exists());
}

#[test]
fn structural_ir_json_keeps_source_spelling_and_reports_original_partial_string_instructions() {
    let root = tempfile::tempdir().unwrap();
    let manifest = resources(root.path());
    std::fs::write(
        root.path().join("code.py"),
        "def f():\n    return \"\\ud800\"\n",
    )
    .unwrap();
    for view in ["source", "instructions"] {
        let output = command(
            root.path(),
            &manifest,
            &[
                "structural",
                "ir",
                "--scope",
                "code.py",
                "--cache-mb",
                "0",
                "--view",
                view,
                "--json",
            ],
        );
        assert!(
            output.status.success(),
            "{view}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        let raw = std::str::from_utf8(&output.stdout).unwrap();
        let _: Box<serde_json::value::RawValue> = serde_json::from_str(raw).unwrap();
        if view == "source" {
            assert!(raw.contains("\\ud800"), "{view}: {raw}");
        } else {
            let data: Value = serde_json::from_str(raw).unwrap();
            assert_eq!(data["ir"]["functions"][0]["status"], "partial");
            assert_eq!(
                data["ir"]["functions"][0]["reasons"],
                json!(["expression-lowering:string"])
            );
        }
    }
}
