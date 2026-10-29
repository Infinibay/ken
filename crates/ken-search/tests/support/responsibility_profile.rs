use super::support::Fixture;
use flate2::read::GzDecoder;
use rusqlite::{Connection, params};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::io::Read;

pub fn reference() -> Value {
    let bytes = include_bytes!("../fixtures/responsibility-profile-reference.json.gz");
    assert_eq!(bytes.len(), 1579);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "947062689930f5f7c0404fdec13b2d9d07a22fc36a9eaf160e6e1825e04b12ea"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    let value: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(value["rows"].as_array().unwrap().len(), 16);
    assert_eq!(value["public"].as_array().unwrap().len(), 5);
    value
}
pub fn fixture() -> Fixture {
    let fixture = Fixture::new();
    let conn = Connection::open(fixture.paths.db()).unwrap();
    conn.execute_batch("DELETE FROM ci_imports; DELETE FROM ci_symbols; DELETE FROM ci_intent_sources; DELETE FROM ci_files").unwrap();
    for (id, file) in reference()["input"]["files"]
        .as_array()
        .unwrap()
        .iter()
        .enumerate()
    {
        let id = id as i64 + 1;
        conn.execute("INSERT INTO ci_files(id,path,language,content_hash,symbol_count,mtime,indexed_at)VALUES(?1,?2,'python',?3,1,0,1)", params![id, file["path"].as_str().unwrap(), b"hash"]).unwrap();
        conn.execute("INSERT INTO ci_symbols(file_id,kind,name,qualname,line_start,line_end,docstring)VALUES(?1,'function','get',NULL,1,1,?2)", params![id, file["text"].as_str().unwrap()]).unwrap();
        if let Some(text) = file["intent"].as_str() {
            conn.execute("INSERT INTO ci_intent_sources(file_id,source_kind,text,updated_at)VALUES(?1,'module_docstring',?2,0)", params![id, text]).unwrap();
        }
    }
    fixture
}
