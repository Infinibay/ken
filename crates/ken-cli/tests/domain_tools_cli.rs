#[path = "../../ken-search/tests/support/navigation.rs"]
#[allow(dead_code)]
mod support;
use serde_json::{Value, json};
use std::process::Command;
use support::Fixture;
fn call(fixture: &Fixture, args: &[&str]) -> Value {
    let output = Command::new(env!("CARGO_BIN_EXE_ken-rs"))
        .arg("--resources")
        .arg(fixture.paths.root().join("missing.json"))
        .arg("tools")
        .arg("--path")
        .arg(fixture.paths.root())
        .args(args)
        .arg("--output-format")
        .arg("json")
        .env_clear()
        .env("HOME", fixture.paths.root())
        .env("PATH", "")
        .env(
            "KEN_GIT_PROGRAM",
            std::env::var_os("KEN_GIT_PROGRAM").unwrap(),
        )
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
fn native_module_tools_persist_paginate_cas_and_delete_without_python_models_or_grammars() {
    let fixture = Fixture::new();
    let source =
        "language \"kql/2\";module team;query classes {edge ENTITY($c,\"CLASS\");select $c;}";
    let saved = call(
        &fixture,
        &[
            "query", "--action", "save", "--module", "team", "--source", source,
        ],
    );
    assert_eq!(saved["module"], "team");
    assert!(saved["revision"].is_string());
    let listed = call(&fixture, &["query", "--prefix", "tea", "--limit", "1"]);
    assert_eq!(listed["total"], 1);
    assert_eq!(listed["modules"].as_array().unwrap().len(), 1);
    assert!(listed["modules"][0].get("source").is_none());
    let shown = call(
        &fixture,
        &["ken_query", "--action", "show", "--module", "team"],
    );
    assert_eq!(shown["source"], source);
    let changed = format!("{source}\n");
    let updated = call(
        &fixture,
        &[
            "query",
            "--action",
            "save",
            "--source",
            &changed,
            "--expected-revision",
            saved["revision"].as_str().unwrap(),
        ],
    );
    assert_ne!(updated["revision"], saved["revision"]);
    let deleted = call(
        &fixture,
        &[
            "query",
            "--action",
            "delete",
            "--module",
            "team",
            "--expected-revision",
            updated["revision"].as_str().unwrap(),
        ],
    );
    assert_eq!(deleted, json!({"deleted":"team"}));
    assert_eq!(call(&fixture, &["query"])["total"], 0);
}
#[test]
fn exact_calculation_tools_expose_domain_results_and_errors_without_opening_the_index() {
    let fixture = Fixture::new();
    let before = fixture.database_hash();
    let result = call(&fixture, &["calculate", "1 / 3 + 2 / 3"]);
    assert_eq!(result["exact"], "1");
    assert_eq!(result["stored_as_premise"], false);
    let error = call(&fixture, &["ken_calculate", "open('secret')"]);
    assert_eq!(error["ok"], false);
    assert!(error["error"].is_string());
    assert_eq!(fixture.database_hash(), before);
}
#[test]
fn structural_find_executes_live_legacy_kql2_and_saved_queries_with_zero_cache_and_no_models() {
    let fixture = Fixture::new();
    let manifest = fixture.paths.root().join("missing.json");
    std::fs::write(&manifest,json!({"format":"ken-search-installation/1","grammar_manifest":std::path::PathBuf::from(std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap())}).to_string()).unwrap();
    std::fs::write(
        fixture.paths.root().join("public_native.py"),
        "class NativeAlpha: pass\n",
    )
    .unwrap();
    let legacy = call(
        &fixture,
        &[
            "find",
            "require $unit ENTITY CLASS",
            "--scope",
            "structure",
            "--source-path",
            "public_native.py",
            "--cache-mb",
            "0",
        ],
    );
    assert_eq!(legacy["matches"].as_array().unwrap().len(), 1);
    assert_eq!(legacy["matches"][0]["path"], "public_native.py");
    let modern = "language \"kql/2\";module public_native;query classes{class $c{}select $c;}";
    let kql = call(
        &fixture,
        &[
            "find",
            modern,
            "--scope",
            "structure",
            "--query-language",
            "kql/2",
            "--source-path",
            "public_native.py",
            "--cache-mb",
            "0",
        ],
    );
    assert_eq!(kql["rows"].as_array().unwrap().len(), 1);
    assert_eq!(kql["complete"], true);
    call(&fixture, &["query", "--action", "save", "--source", modern]);
    let saved = call(
        &fixture,
        &[
            "find",
            "--scope",
            "structure",
            "--query-language",
            "kql/2",
            "--saved-query",
            "public_native",
            "--source-path",
            "public_native.py",
            "--cache-mb",
            "0",
        ],
    );
    assert_eq!(saved["rows"], kql["rows"]);
    std::fs::write(
        fixture.paths.root().join("public_native.py"),
        "class NativeBeta: pass\nclass NativeGamma: pass\n",
    )
    .unwrap();
    let changed = call(
        &fixture,
        &[
            "find",
            modern,
            "--scope",
            "structure",
            "--query-language",
            "kql/2",
            "--source-path",
            "public_native.py",
            "--cache-mb",
            "0",
        ],
    );
    assert_eq!(changed["rows"].as_array().unwrap().len(), 2);
}
#[test]
fn contracts_history_and_scoped_source_relations_reach_native_owners() {
    let fixture = Fixture::new();
    std::fs::write(fixture.paths.root().join("missing.json"),json!({"format":"ken-search-installation/1","grammar_manifest":std::path::PathBuf::from(std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap())}).to_string()).unwrap();
    let definition=json!({"id":"cli.source","description":"A source contract","path":"src","expectation":"some_match","query":"language \"kql/2\";module cli_contract;query q{select 1;}","examples":[]}).to_string();
    let created = call(
        &fixture,
        &["rule", "--action", "create", "--definition", &definition],
    );
    assert!(created.to_string().contains("cli.source"));
    let listed = call(&fixture, &["ken_rule"]);
    assert!(listed.to_string().contains("cli.source"));
    let checks = call(&fixture, &["related", "src/service.py", "checks"]);
    assert!(checks.to_string().contains("cli.source"));
    let history = call(&fixture, &["related", "src/service.py", "cochange"]);
    assert!(history.get("partners").is_some());
    let clones = call(&fixture, &["related", "src/service.py", "clones"]);
    assert!(clones.get("ok").is_some());
    std::fs::write(fixture.paths.root().join("public_native.py"),"def emit(value): return value\ndef relay(value): return emit(value)\ndef use(): return relay(1)\n").unwrap();
    let impact = call(
        &fixture,
        &[
            "related",
            "public_native.py::relay",
            "impact",
            "--analysis-path",
            "public_native.py",
            "--depth",
            "2",
        ],
    );
    assert!(!impact["targets"].as_array().unwrap().is_empty());
    assert!(impact["contracts"].is_array());
    assert!(
        impact["consumers"]
            .as_array()
            .unwrap()
            .iter()
            .any(|item| item["caller"]["symbol"] == "use")
    );
}
