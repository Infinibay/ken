use base64::{Engine, engine::general_purpose::STANDARD};
use flate2::read::GzDecoder;
use ken_core::{
    project::{DiscoveryContext, ProjectPaths},
    tool_output::Document,
};
use ken_search::navigation::{IndexNavigation, ReadRequest};
use ken_store::ProjectDatabase;
use rusqlite::params;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{fs, io::Read};

pub fn reference() -> Value {
    let bytes = include_bytes!("../fixtures/index-navigation-reference.json.gz");
    assert_eq!(bytes.len(), 4580);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "5d8140a9c79d558412201aa1f22d6bd2b207b6dacefe5ad47ce7a4c2f62fbae3"
    );
    let mut text = String::new();
    GzDecoder::new(&bytes[..])
        .read_to_string(&mut text)
        .unwrap();
    let result: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(result["rows"].as_array().unwrap().len(), 49);
    assert_eq!(result["public"].as_array().unwrap().len(), 19);
    result
}
pub struct Fixture {
    pub _directory: tempfile::TempDir,
    pub paths: ProjectPaths,
}
impl Fixture {
    pub fn new() -> Self {
        let value = reference();
        let directory = tempfile::tempdir().unwrap();
        let root = directory.path().join("project");
        fs::create_dir_all(root.join(".ken")).unwrap();
        fs::write(
            root.join(".ken/meta.json"),
            r#"{"project_id":{"name":"navigation"}}"#,
        )
        .unwrap();
        let paths = ProjectPaths::at(
            &root,
            &DiscoveryContext {
                cwd: root.clone(),
                home: None,
                forced_root: None,
            },
        )
        .unwrap();
        let mut db = ProjectDatabase::open(&paths.db()).unwrap();
        db.initialize().unwrap();
        let conn = db.connection();
        for f in value["input"]["files"].as_array().unwrap() {
            if let Some(text) = f["source"].as_str() {
                let path = root.join(f["path"].as_str().unwrap());
                fs::create_dir_all(path.parent().unwrap()).unwrap();
                fs::write(
                    path,
                    if f["binary"] == true {
                        STANDARD.decode(text).unwrap()
                    } else {
                        text.as_bytes().to_vec()
                    },
                )
                .unwrap();
            }
            conn.execute("INSERT INTO ci_files(id,path,language,content_hash,symbol_count,mtime,indexed_at)VALUES(?1,?2,?3,?4,?5,0,?6)",params![f["id"].as_i64().unwrap(),f["path"].as_str().unwrap(),f["language"].as_str(),b"hash",f["symbol_count"].as_i64().unwrap(),f["indexed_at"].as_i64().unwrap()]).unwrap();
            for s in f["symbols"].as_array().unwrap() {
                conn.execute("INSERT INTO ci_symbols(file_id,kind,name,qualname,line_start,line_end,docstring)VALUES(?1,?2,?3,?4,?5,?6,?7)",params![f["id"].as_i64().unwrap(),s[0].as_str().unwrap(),s[1].as_str().unwrap(),s[2].as_str(),s[3].as_i64().unwrap(),s[4].as_i64().unwrap(),s[5].as_str()]).unwrap();
            }
        }
        for r in value["input"]["imports"].as_array().unwrap() {
            conn.execute(
                "INSERT INTO ci_imports(from_file_id,to_module,to_file_id,line)VALUES(?1,?2,?3,?4)",
                params![
                    r[0].as_i64().unwrap(),
                    r[1].as_str().unwrap(),
                    r[2].as_i64(),
                    r[3].as_i64().unwrap()
                ],
            )
            .unwrap();
        }
        for r in value["input"]["module_docs"].as_array().unwrap() {
            conn.execute("INSERT INTO ci_intent_sources(file_id,source_kind,text,updated_at)VALUES(?1,'module_docstring',?2,0)",params![r[0].as_i64().unwrap(),r[1].as_str().unwrap()]).unwrap();
        }
        Self {
            _directory: directory,
            paths,
        }
    }
    pub fn database_hash(&self) -> String {
        format!("{:x}", Sha256::digest(fs::read(self.paths.db()).unwrap()))
    }
    pub fn expand(&self, path: &str) -> String {
        path.strip_prefix("ABS:").map_or_else(
            || path.to_owned(),
            |p| self.paths.root().join(p).to_string_lossy().into_owned(),
        )
    }
}
pub fn document_value(value: &Document) -> Value {
    serde_json::to_value(value).unwrap()
}
pub fn domain(nav: &IndexNavigation, fixture: &Fixture, row: &Value) -> Document {
    let args = &row["request"]["args"];
    let path = fixture.expand(args["path"].as_str().unwrap_or(""));
    let flag = |key: &str, default| args[key].as_bool().unwrap_or(default);
    let number = |key: &str, default| args[key].as_i64().unwrap_or(default);
    match row["request"]["op"].as_str().unwrap() {
        "file_symbols" => nav.file_symbols(&path, flag("include_docstrings", true)),
        "file_outline" => nav.file_outline(
            &path,
            flag("include_symbols", true),
            flag("include_imports", true),
            flag("include_docstrings", true),
        ),
        "symbol_detail" => nav.symbol_detail(
            &path,
            args["qualname"].as_str().unwrap(),
            flag("include_snippet", false),
        ),
        "file_snippets" => nav.file_snippets(
            &path,
            &args["symbols"]
                .as_array()
                .map(|v| {
                    v.iter()
                        .map(|s| s.as_str().unwrap().to_owned())
                        .collect::<Vec<_>>()
                })
                .unwrap_or_default(),
            args["start_line"].as_i64(),
            args["end_line"].as_i64(),
            number("max_chars", 12000),
        ),
        "find_tests" => nav.find_tests(&path, number("limit", 20)),
        "file_neighbors" => nav.file_neighbors(&path, number("limit", 20)),
        "module_graph" => nav.module_graph(&path, number("depth", 1), number("limit", 100)),
        "project_overview" => nav.project_overview(number("depth", 2), number("limit", 20)),
        _ => panic!("unknown original operation"),
    }
    .unwrap()
}
pub fn public(nav: &IndexNavigation, row: &Value) -> Document {
    let args = &row["request"]["args"];
    match row["request"]["tool"].as_str().unwrap() {
        "ken_read" => nav.read(&serde_json::from_value::<ReadRequest>(args.clone()).unwrap()),
        "ken_related" => nav.related(
            args["target"].as_str().unwrap(),
            args["relation"].as_str().unwrap(),
            args["depth"].as_i64().unwrap_or(1),
            args["limit"].as_i64().unwrap_or(10),
        ),
        "ken_find" => nav.test_search(
            args["query"].as_str().unwrap(),
            args["limit"].as_i64().unwrap_or(10),
        ),
        _ => panic!("unknown public operation"),
    }
    .unwrap()
}
#[allow(dead_code)] // Also consumed by the CLI integration target.
pub fn cli_args(row: &Value, json_output: bool) -> Vec<String> {
    let request = &row["request"];
    let args = &request["args"];
    let mut result = vec!["tools".into()];
    if json_output {
        result.push("--json".into());
    }
    match request["tool"].as_str().unwrap() {
        "ken_read" => {
            result.extend(["read".into(), args["path"].as_str().unwrap().into()]);
            for key in ["qualname", "start_line", "end_line", "max_chars"] {
                if !args[key].is_null() {
                    result.extend([
                        format!("--{}", key.replace('_', "-")),
                        args[key]
                            .as_str()
                            .map(str::to_owned)
                            .unwrap_or_else(|| args[key].to_string()),
                    ]);
                }
            }
            if let Some(v) = args["include"].as_array().filter(|v| !v.is_empty()) {
                result.push("--include".into());
                result.extend(v.iter().map(|v| v.as_str().unwrap().to_owned()));
            }
        }
        "ken_related" => {
            result.extend([
                "related".into(),
                args["target"].as_str().unwrap().into(),
                args["relation"].as_str().unwrap().into(),
            ]);
            for key in ["depth", "limit"] {
                if !args[key].is_null() {
                    result.extend([format!("--{key}"), args[key].to_string()]);
                }
            }
        }
        "ken_find" => {
            result.extend([
                "find".into(),
                args["query"].as_str().unwrap().into(),
                "--scope".into(),
                "tests".into(),
            ]);
        }
        _ => panic!("unknown public operation"),
    }
    result
}
