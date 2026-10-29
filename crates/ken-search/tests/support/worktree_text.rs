use super::support::{Fixture, reference as navigation_reference};
use flate2::read::GzDecoder;
use ken_index::changes::content_hash;
use rusqlite::{Connection, params};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{fs, io::Read};

pub fn reference() -> Value {
    let bytes = include_bytes!("../fixtures/worktree-text-reference.json.gz");
    assert_eq!(bytes.len(), 1949);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "75a95de020973bcaba8e06a1e2eeeffb5c85e28768a35649d5a1c8798f580396"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    let value: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(value["rows"].as_array().unwrap().len(), 29);
    value
}
pub fn fixture() -> Fixture {
    let fixture = Fixture::new();
    let conn = Connection::open(fixture.paths.db()).unwrap();
    for file in navigation_reference()["input"]["files"].as_array().unwrap() {
        let path = file["path"].as_str().unwrap();
        let Ok(bytes) = fs::read(fixture.paths.root().join(path)) else {
            continue;
        };
        conn.execute(
            "INSERT INTO fts_files(path,body)VALUES(?1,?2)",
            params![path, String::from_utf8_lossy(&bytes)],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO ci_fts_state(path,content_hash)VALUES(?1,?2)",
            params![path, content_hash(&bytes).as_slice()],
        )
        .unwrap();
    }
    fixture
}
pub fn apply(fixture: &Fixture, event: &Value) {
    let path = event["path"].as_str().unwrap();
    match event["action"].as_str().unwrap() {
        "write" => fs::write(
            fixture.paths.root().join(path),
            event["text"].as_str().unwrap(),
        )
        .unwrap(),
        "delete" => fs::remove_file(fixture.paths.root().join(path)).unwrap(),
        "unindex" => {
            Connection::open(fixture.paths.db())
                .unwrap()
                .execute("DELETE FROM ci_files WHERE path=?1", [path])
                .unwrap();
        }
        _ => panic!("unknown history mutation: {event}"),
    }
}
#[allow(dead_code)] // Used by the CLI integration target.
pub fn cli_args(args: &Value, json: bool) -> Vec<String> {
    let mut result = vec!["tools".into()];
    if json {
        result.push("--json".into());
    }
    result.extend([
        "find".into(),
        args["query"].as_str().unwrap().into(),
        "--scope".into(),
        "text".into(),
    ]);
    if args["literal"] == true {
        result.push("--literal".into());
    }
    if let Some(language) = args["language"].as_str() {
        result.extend(["--language".into(), language.into()]);
    }
    if let Some(limit) = args["limit"].as_i64() {
        result.extend(["--limit".into(), limit.to_string()]);
    }
    result
}
