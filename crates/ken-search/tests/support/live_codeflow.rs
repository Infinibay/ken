use super::support::Fixture;
use flate2::read::GzDecoder;
use rusqlite::{Connection, params};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{fs, io::Read, path::PathBuf};
pub fn reference() -> Value {
    let bytes = include_bytes!("../fixtures/live-codeflow-reference.json.gz");
    assert_eq!(bytes.len(), 3413);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "b5586fe9eae7915b49c44f8da201deda952aaa8bf6e87911882fa83028055969"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    let value: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(value["signals"].as_array().unwrap().len(), 19);
    assert_eq!(value["rows"].as_array().unwrap().len(), 26);
    assert_eq!(value["public"].as_array().unwrap().len(), 10);
    value
}
pub fn fixture() -> Fixture {
    let fixture = Fixture::new();
    let mut conn = Connection::open(fixture.paths.db()).unwrap();
    conn.execute_batch("DELETE FROM ci_imports;DELETE FROM ci_symbols;DELETE FROM ci_intent_sources;DELETE FROM ci_files").unwrap();
    let tx = conn.transaction().unwrap();
    let reference = reference();
    let files = reference["input"]["files"].as_array().unwrap();
    for (i, file) in files.iter().enumerate() {
        let id = i as i64 + 1;
        let path = file["path"].as_str().unwrap();
        if let Some(source) = file["source"].as_str() {
            fs::write(fixture.paths.root().join(path), source).unwrap();
        }
        tx.execute("INSERT INTO ci_files(id,path,language,content_hash,symbol_count,mtime,indexed_at)VALUES(?1,?2,?3,?4,?5,0,1)",params![id,path,file["language"].as_str().unwrap(),b"hash",file["symbols"].as_array().unwrap().len()as i64]).unwrap();
        for symbol in file["symbols"].as_array().unwrap() {
            tx.execute("INSERT INTO ci_symbols(file_id,kind,name,qualname,line_start,line_end)VALUES(?1,?2,?3,?4,?5,?6)",params![id,symbol[2].as_str().unwrap(),symbol[0].as_str().unwrap(),symbol[1].as_str().unwrap(),symbol[3].as_i64().unwrap(),symbol[4].as_i64().unwrap()]).unwrap();
        }
    }
    for (i, file) in files.iter().enumerate() {
        for import in file["imports"].as_array().unwrap() {
            let to = files.iter().position(|f| f["path"] == *import).unwrap() as i64 + 1;
            tx.execute(
                "INSERT INTO ci_imports(from_file_id,to_module,to_file_id,line)VALUES(?1,?2,?3,1)",
                params![i as i64 + 1, import.as_str().unwrap(), to],
            )
            .unwrap();
        }
    }
    tx.commit().unwrap();
    fixture
}
pub fn grammar_manifest() -> PathBuf {
    std::env::var_os("KEN_GRAMMAR_MANIFEST")
        .expect("prepared native grammars")
        .into()
}
pub fn installation(fixture: &Fixture) {
    fs::write(
        fixture.paths.root().join("missing-installation.json"),
        json!({"format":"ken-search-installation/1","grammar_manifest":grammar_manifest()})
            .to_string(),
    )
    .unwrap();
}
pub fn cli_args(row: &Value, json_output: bool) -> Vec<String> {
    let req = &row["request"];
    let args = &req["args"];
    let mut result = vec!["tools".into()];
    if json_output {
        result.push("--json".into());
    }
    if req["tool"] == "ken_related" {
        result.extend([
            "related".into(),
            args["target"].as_str().unwrap().into(),
            args["relation"].as_str().unwrap().into(),
        ]);
        if let Some(c) = args["min_confidence"].as_f64() {
            result.extend(["--min-confidence".into(), c.to_string()]);
        }
    } else {
        result.extend([
            "find".into(),
            args["query"].as_str().unwrap().into(),
            "--scope".into(),
            "wiring".into(),
        ]);
    }
    if let Some(limit) = args["limit"].as_i64() {
        result.extend(["--limit".into(), limit.to_string()]);
    }
    if args["full"] == true {
        result.push("--full".into());
    }
    result
}
