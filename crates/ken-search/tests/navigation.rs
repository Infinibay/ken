#[path = "support/navigation.rs"]
mod support;
use ken_core::tool_output::{Document, render};
use ken_search::navigation::{IndexNavigation, ReadRequest};
use std::fs;
use support::*;

#[test]
fn original_navigation_and_public_text_match_without_models_or_index_writes() {
    let fixture = Fixture::new();
    let hash = fixture.database_hash();
    let reference = reference();
    let nav = IndexNavigation::open(&fixture.paths).unwrap();
    for row in reference["rows"].as_array().unwrap() {
        assert_eq!(
            document_value(&domain(&nav, &fixture, row)),
            row["result"],
            "{}",
            row["request"]
        );
    }
    for row in reference["public"].as_array().unwrap() {
        let value = public(&nav, row);
        assert_eq!(document_value(&value), row["result"], "{}", row["request"]);
        assert_eq!(
            render(&value, row["request"]["tool"].as_str().unwrap(), false),
            row["compact"].as_str().unwrap(),
            "{}",
            row["request"]
        );
        let encoded = serde_json::to_string(&value).unwrap();
        let decoded: Document = serde_json::from_str(&encoded).unwrap();
        assert_eq!(decoded, value);
    }
    drop(nav);
    assert_eq!(fixture.database_hash(), hash);
    assert!(!fixture.paths.root().join("cache").exists());
}
#[test]
fn source_is_confined_and_each_navigation_view_opens_the_current_database() {
    let fixture = Fixture::new();
    let outside = tempfile::tempdir().unwrap();
    fs::write(outside.path().join("private.py"), "private source").unwrap();
    std::os::unix::fs::symlink(
        outside.path().join("private.py"),
        fixture.paths.root().join("escape.py"),
    )
    .unwrap();
    // On Unix a backslash belongs to the filename; it is not a separator.
    fs::write(
        fixture.paths.root().join("literal\\name.py"),
        "literal backslash\n",
    )
    .unwrap();
    let connection = rusqlite::Connection::open(fixture.paths.db()).unwrap();
    connection
        .execute(
            "INSERT INTO ci_files(path,content_hash,mtime,indexed_at)VALUES(?1,?2,0,0)",
            rusqlite::params!["literal\\name.py", b"hash"],
        )
        .unwrap();
    drop(connection);
    let nav = IndexNavigation::open(&fixture.paths).unwrap();
    let literal = nav
        .read(&ReadRequest {
            path: "literal\\name.py".into(),
            include: Some(vec!["source".into()]),
            start_line: 1,
            end_line: 1,
            ..Default::default()
        })
        .unwrap();
    assert_eq!(literal.get("path").string(), Some("literal\\name.py"));
    assert_eq!(
        literal.get("source").get("snippets").array()[0]
            .get("code")
            .string(),
        Some("1: literal backslash")
    );
    for path in ["../private.py", "escape.py"] {
        assert!(
            nav.read(&ReadRequest {
                path: path.into(),
                include: Some(vec!["source".into()]),
                ..Default::default()
            })
            .is_err()
        );
    }
    assert!(nav.related("src/service.py", "callers", 1, 10).is_err());
    drop(nav);
    let replacement = Fixture::new();
    let conn = rusqlite::Connection::open(replacement.paths.db()).unwrap();
    conn.execute(
        "UPDATE ci_symbols SET docstring='replacement' WHERE qualname='Service'",
        [],
    )
    .unwrap();
    drop(conn);
    fs::rename(replacement.paths.db(), fixture.paths.db()).unwrap();
    let current = IndexNavigation::open(&fixture.paths).unwrap();
    assert_eq!(
        current
            .symbol_detail("src/service.py", "Service", false)
            .unwrap()
            .get("symbol")
            .get("docstring")
            .string(),
        Some("replacement")
    );
}
