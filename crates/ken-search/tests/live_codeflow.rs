#[path = "support/live_codeflow.rs"]
#[allow(dead_code)]
mod live;
#[path = "support/navigation.rs"]
#[allow(dead_code)]
mod support;
use ken_core::tool_output::render;
use ken_search::navigation::{CallGraphRequest, IndexNavigation};
use ken_syntax::{GrammarCatalog, signals};
use serde_json::{Value, json};
use std::fs;
#[test]
fn original_syntax_signals_resolution_hierarchy_and_public_tools_match_live_source() {
    let reference = live::reference();
    let catalog = GrammarCatalog::prepared(&live::grammar_manifest()).unwrap();
    let fixture = live::fixture();
    let hash = fixture.database_hash();
    let nav = IndexNavigation::open(&fixture.paths).unwrap();
    for (file, row) in reference["input"]["files"]
        .as_array()
        .unwrap()
        .iter()
        .zip(reference["signals"].as_array().unwrap())
    {
        let signals = signals::extract(
            &catalog,
            file["language"].as_str().unwrap(),
            file["source"].as_str().unwrap_or("").as_bytes(),
        )
        .unwrap();
        assert_eq!(
            serde_json::to_value(signals).unwrap(),
            row["result"],
            "{}",
            file["path"]
        );
    }
    for row in reference["rows"].as_array().unwrap() {
        let request = &row["request"];
        let args = &request["args"];
        let got = match request["op"].as_str().unwrap() {
            "callgraph" => nav.callgraph(
                &catalog,
                &serde_json::from_value::<CallGraphRequest>(args.clone()).unwrap(),
            ),
            "type_hierarchy" => nav.type_hierarchy(
                &catalog,
                args["qualname"].as_str().unwrap(),
                args["direction"].as_str().unwrap(),
                args["with_overrides"].as_bool().unwrap(),
            ),
            "wiring" => nav.wiring(
                &catalog,
                args["query"].as_str().unwrap_or(""),
                args["trigger_kind"].as_str().unwrap_or(""),
                args["limit"].as_i64().unwrap_or(50),
            ),
            _ => panic!("unknown original operation"),
        }
        .unwrap();
        assert_eq!(
            serde_json::to_value(got).unwrap(),
            row["result"],
            "{request}"
        );
    }
    for row in reference["public"].as_array().unwrap() {
        let request = &row["request"];
        let args = &request["args"];
        let relation = args["relation"].as_str().unwrap_or("");
        let got = if request["tool"] == "ken_find" {
            nav.wiring(
                &catalog,
                args["query"].as_str().unwrap(),
                "",
                args["limit"].as_i64().unwrap_or(10),
            )
        } else if matches!(relation, "callers" | "callees") {
            nav.callgraph(
                &catalog,
                &CallGraphRequest {
                    qualname: args["target"].as_str().unwrap().into(),
                    direction: relation.into(),
                    min_confidence: args["min_confidence"].as_f64().unwrap_or(0.0).into(),
                    limit: args["limit"].as_i64().unwrap_or(10),
                    ..Default::default()
                },
            )
        } else {
            nav.type_hierarchy(
                &catalog,
                args["target"].as_str().unwrap(),
                if relation == "subtypes" { "down" } else { "up" },
                true,
            )
        }
        .unwrap();
        assert_eq!(
            serde_json::to_value(&got).unwrap(),
            row["result"],
            "{request}"
        );
        assert_eq!(
            render(
                &got,
                request["tool"].as_str().unwrap(),
                args["full"] == true
            ),
            row["compact"].as_str().unwrap(),
            "{request}"
        );
    }
    assert_eq!(fixture.database_hash(), hash);
    fs::remove_file(fixture.paths.root().join("duplicate.py")).unwrap();
    let hierarchy: Value =
        serde_json::to_value(nav.type_hierarchy(&catalog, "Base", "sub", true).unwrap()).unwrap();
    assert_eq!(
        hierarchy["descendants"],
        json!(["App", "Child", "Dog", "Grand"])
    );
    assert_eq!(
        hierarchy["overrides"],
        json!([{"class":"Child","overrides":["speak"],"confidence":"best-effort"}])
    );
    let outside = fixture._directory.path().join("outside.py");
    fs::write(&outside, "helper()\n").unwrap();
    fs::remove_file(fixture.paths.root().join("api.py")).unwrap();
    std::os::unix::fs::symlink(&outside, fixture.paths.root().join("api.py")).unwrap();
    let calls = nav
        .callgraph(
            &catalog,
            &CallGraphRequest {
                qualname: "run".into(),
                direction: "callees".into(),
                ..Default::default()
            },
        )
        .unwrap();
    assert!(calls.get("callees").array().is_empty());
}
