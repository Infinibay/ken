use super::support::Fixture;
use flate2::read::GzDecoder;
use rusqlite::{Connection, params};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{fs, io::Read, process::Command};

pub fn reference() -> Value {
    let bytes = include_bytes!("../fixtures/project-orientation-reference.json.gz");
    assert_eq!(bytes.len(), 24430);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "c6813356a1dfaeb9a9bcc19700a47cadfec8f6f18bf46d45ecb43b6ac4ef51c7"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    let value: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(value["cases"].as_array().unwrap().len(), 6);
    assert_eq!(value["changes"].as_array().unwrap().len(), 2);
    value
}
pub fn graph_fixture(case: &Value) -> Fixture {
    let fixture = Fixture::new();
    let mut conn = Connection::open(fixture.paths.db()).unwrap();
    conn.execute_batch("PRAGMA foreign_keys=OFF; DELETE FROM ci_imports; DELETE FROM ci_symbols; DELETE FROM ci_intent_sources; DELETE FROM ci_files").unwrap();
    let tx = conn.transaction().unwrap();
    for file in case["files"].as_array().unwrap() {
        tx.execute("INSERT INTO ci_files(id,path,language,content_hash,symbol_count,mtime,indexed_at)VALUES(?1,?2,'python',?3,?4,0,1)", params![file["id"].as_i64().unwrap(), file["path"].as_str().unwrap(), b"hash", file["symbols"].as_i64().unwrap()]).unwrap();
    }
    for (i, edge) in case["edges"].as_array().unwrap().iter().enumerate() {
        tx.execute("INSERT INTO ci_imports(from_file_id,to_module,to_file_id,line,resolution)VALUES(?1,'module',?2,?3,?4)", params![edge[0].as_i64().unwrap(), edge[1].as_i64(), i as i64+1, edge[2].as_str().unwrap()]).unwrap();
    }
    tx.commit().unwrap();
    fixture
}
fn git(fixture: &Fixture, args: &[&str]) {
    let got = Command::new("git")
        .args([
            "-c",
            "user.name=ken",
            "-c",
            "user.email=ken@local",
            "-c",
            "commit.gpgsign=false",
        ])
        .args(args)
        .current_dir(fixture.paths.root())
        .output()
        .unwrap();
    assert!(
        got.status.success(),
        "git {args:?}: {}",
        String::from_utf8_lossy(&got.stderr)
    );
}
pub fn changes_fixture() -> Fixture {
    let fixture = Fixture::new();
    let root = fixture.paths.root();
    fs::write(root.join(".gitignore"), ".ken/\n").unwrap();
    git(&fixture, &["init", "-q"]);
    git(&fixture, &["config", "core.quotePath", "true"]);
    git(&fixture, &["add", "."]);
    git(&fixture, &["commit", "-qm", "fixture"]);
    let mut service = fs::read(root.join("src/service.py")).unwrap();
    service.extend_from_slice(b"\n# worktree change\n");
    fs::write(root.join("src/service.py"), service).unwrap();
    fs::remove_file(root.join("src/base.py")).unwrap();
    git(&fixture, &["mv", "src/utils.py", "src/renamed file.py"]);
    fs::write(root.join("new file.py"), "new source\n").unwrap();
    fs::write(root.join("nuevo_é.py"), "unicode\n").unwrap();
    fs::create_dir(root.join("untracked_dir")).unwrap();
    fs::write(root.join("untracked_dir/new.py"), "new\n").unwrap();
    let mut test = fs::read(root.join("tests/test_service.py")).unwrap();
    test.extend_from_slice(b"\n# staged\n");
    fs::write(root.join("tests/test_service.py"), test).unwrap();
    git(&fixture, &["add", "tests/test_service.py"]);
    fixture
}
pub fn cli_args(args: &Value, json: bool) -> Vec<String> {
    let mut result = vec!["tools".into()];
    if json {
        result.push("--json".into());
    }
    result.extend([
        "rank".into(),
        args["query"].as_str().unwrap_or("").into(),
        "--scope".into(),
        args["scope"].as_str().unwrap().into(),
    ]);
    for key in ["verbose", "max_chars"] {
        if let Some(value) = args[key].as_i64() {
            result.extend([format!("--{}", key.replace('_', "-")), value.to_string()]);
        }
    }
    if args["explain"] == true {
        result.push("--explain".into());
    }
    result
}
