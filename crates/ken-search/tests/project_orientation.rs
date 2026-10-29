#[path = "support/project_orientation.rs"]
#[allow(dead_code)]
mod orientation;
#[path = "support/navigation.rs"]
#[allow(dead_code)]
mod support;
use ken_core::tool_output::{Document, render};
use ken_search::navigation::IndexNavigation;
use serde_json::{Value, json};

fn compare(got: &Document, row: &Value) {
    assert_eq!(
        serde_json::to_value(got).unwrap(),
        row["result"],
        "{}",
        row["args"]
    );
    if let Some(text) = row["compact"].as_str() {
        assert_eq!(
            render(got, "ken_rank", row["args"]["explain"] == true),
            text,
            "{}",
            row["args"]
        );
    }
}
#[test]
fn original_architecture_and_rank_scopes_match_with_iterative_large_graphs() {
    let reference = orientation::reference();
    for (input, case) in reference["input"]
        .as_array()
        .unwrap()
        .iter()
        .zip(reference["cases"].as_array().unwrap())
    {
        let fixture = orientation::graph_fixture(input);
        let hash = fixture.database_hash();
        let nav = IndexNavigation::open(&fixture.paths).unwrap();
        for row in case["rows"].as_array().unwrap() {
            let args = &row["args"];
            compare(
                &nav.architecture(
                    args["depth"].as_i64().unwrap(),
                    args["limit"].as_i64().unwrap(),
                )
                .unwrap(),
                row,
            );
        }
        for row in case["public"].as_array().unwrap() {
            let limit = row["args"]["verbose"].as_i64().unwrap().max(1) * 10;
            let got = if row["args"]["scope"] == "project" {
                nav.project_overview(2, limit)
            } else {
                nav.architecture(2, limit)
            }
            .unwrap();
            compare(&got, row);
        }
        assert_eq!(fixture.database_hash(), hash);
        assert_eq!(nav.changed_context().unwrap().get("changed").array(), &[]);
    }
    let count = 12000;
    let case = json!({"files":(1..=count).map(|id|json!({"id":id,"path":format!("src/unit{id}.py"),"symbols":0})).collect::<Vec<_>>(),"edges":(1..=count).map(|id|json!([id,id%count+1,"resolved"])).collect::<Vec<_>>()});
    let fixture = orientation::graph_fixture(&case);
    let got = IndexNavigation::open(&fixture.paths)
        .unwrap()
        .architecture(1, 1)
        .unwrap();
    assert_eq!(got.get("summary").get("graph_files").integer(), Some(count));
    assert_eq!(
        got.get("cycles").array()[0].get("size").integer(),
        Some(count)
    );
    assert_eq!(got.get("cycles").array()[0].get("files").array().len(), 1);
}
#[test]
fn original_git_changes_keep_deleted_symbols_and_porcelain_quoting() {
    let fixture = orientation::changes_fixture();
    let hash = fixture.database_hash();
    let nav = IndexNavigation::open(&fixture.paths).unwrap();
    for row in orientation::reference()["changes"].as_array().unwrap() {
        compare(&nav.changed_context().unwrap(), row);
    }
    assert_eq!(fixture.database_hash(), hash);
}
