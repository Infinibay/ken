#[path = "support/worktree_text.rs"]
mod history;
#[path = "support/navigation.rs"]
#[allow(dead_code)]
mod support;
use ken_core::tool_output::render;
use ken_search::text_search::WorktreeTextSearch;
use rusqlite::Connection;
use std::fs;

#[test]
fn live_text_search_matches_original_history_and_atomic_derived_mirror() {
    let reference = history::reference();
    let fixture = history::fixture();
    let search = WorktreeTextSearch::new(fixture.paths.clone());
    let mut rows = reference["rows"].as_array().unwrap().iter();
    for event in reference["events"].as_array().unwrap() {
        if event["action"] != "query" {
            history::apply(&fixture, event);
            continue;
        }
        let row = rows.next().unwrap();
        let args = &row["args"];
        let before = fixture.database_hash();
        let result = search
            .find(
                args["query"].as_str().unwrap(),
                args["literal"] == true,
                args["language"].as_str().unwrap_or(""),
                args["limit"].as_i64().unwrap_or(10),
            )
            .unwrap();
        assert_eq!(
            serde_json::to_value(&result).unwrap(),
            row["result"],
            "{args}"
        );
        assert_eq!(
            render(&result, "ken_find", false),
            row["compact"].as_str().unwrap(),
            "{args}"
        );
        if args["literal"] == true {
            assert_eq!(fixture.database_hash(), before);
        }
    }
    assert!(rows.next().is_none());

    // Cold mirror creation, universal newlines, replacement decoding, source
    // confinement and rollback are checked through the same public service.
    let fixture = history::fixture();
    let search = WorktreeTextSearch::new(fixture.paths.clone());
    let conn = Connection::open(fixture.paths.db()).unwrap();
    conn.execute_batch("DELETE FROM fts_files; DELETE FROM ci_fts_state")
        .unwrap();
    fs::write(
        fixture.paths.root().join("src/base.py"),
        b"UNIQUE_COLD_TEXT\r\nNEXT\rEND\xff",
    )
    .unwrap();
    let get = |query, literal| {
        serde_json::to_value(search.find(query, literal, "python", 10).unwrap()).unwrap()
    };
    assert_eq!(get("NEXT\nEND�", true)["results"][0]["count"], 1);
    assert_eq!(
        get("UNIQUE_COLD_TEXT", false)["results"][0]["path"],
        "src/base.py"
    );
    let before = fixture.database_hash();
    fs::write(
        fixture.paths.root().join("src/base.py"),
        vec![b'x'; 1024 * 1024 + 1],
    )
    .unwrap();
    assert_eq!(
        get("UNIQUE_COLD_TEXT", false)["results"][0]["path"],
        "src/base.py"
    );
    assert_eq!(fixture.database_hash(), before);
    let outside = fixture._directory.path().join("outside.py");
    fs::write(&outside, "OUTSIDE_SEARCH_SECRET").unwrap();
    fs::remove_file(fixture.paths.root().join("src/base.py")).unwrap();
    std::os::unix::fs::symlink(&outside, fixture.paths.root().join("src/base.py")).unwrap();
    assert_eq!(
        get("OUTSIDE_SEARCH_SECRET", true)["results"],
        serde_json::json!([])
    );
    assert_eq!(
        get("OUTSIDE_SEARCH_SECRET", false)["results"],
        serde_json::json!([])
    );
    fs::write(
        fixture.paths.root().join("src/service.py"),
        "ROLLBACK_SENTINEL",
    )
    .unwrap();
    conn.execute_batch("CREATE TRIGGER fail_mirror BEFORE INSERT ON ci_fts_state BEGIN SELECT RAISE(ABORT,'mirror rejected'); END").unwrap();
    let before = fixture.database_hash();
    assert!(search.find("ROLLBACK_SENTINEL", false, "", 10).is_err());
    assert_eq!(fixture.database_hash(), before);
    let leaked: i64 = conn
        .query_row(
            "SELECT count(*) FROM fts_files WHERE body='ROLLBACK_SENTINEL'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(leaked, 0);
}
