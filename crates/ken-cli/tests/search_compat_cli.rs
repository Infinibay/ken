//! Actual command boundaries for evidence and historical search representations.
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_models::RetrievalProfile;
use ken_retrieval::{
    EntityKey, Passage, PassageFields, PassagePolicy, Span, storage::replace_file_passages,
};
use ken_store::ProjectDatabase;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    io::{BufRead, BufReader, Write},
    process::{Command, Output, Stdio},
    sync::mpsc,
    thread,
    time::Duration,
};
struct Fixture {
    root: tempfile::TempDir,
    installation: std::path::PathBuf,
}
impl Fixture {
    fn new(prepared: bool) -> Self {
        let root = tempfile::tempdir().unwrap();
        std::fs::create_dir(root.path().join(".ken")).unwrap();
        std::fs::write(root.path().join(".ken/meta.json"), "{}").unwrap();
        let context = DiscoveryContext {
            cwd: root.path().into(),
            forced_root: None,
            home: Some(root.path().into()),
        };
        let paths = ProjectPaths::at(root.path(), &context).unwrap();
        let mut db = ProjectDatabase::open(&paths.db()).unwrap();
        db.initialize().unwrap();
        if prepared {
            let source = "def target():\n    return 'verified 🦀'\n";
            std::fs::write(root.path().join("source.py"), source).unwrap();
            db.connection().execute("INSERT INTO ci_files(path,content_hash,mtime,indexed_at,language)VALUES('source.py',x'00',0,0,'python')",[]).unwrap();
            db.connection().execute("INSERT INTO ci_symbols(file_id,kind,name,qualname,line_start,line_end)VALUES(1,'function','target','target',1,2)",[]).unwrap();
            let hash = format!("{:x}", Sha256::digest(source.as_bytes()));
            let span = Span::new(1, 2).unwrap();
            let passage = Passage {
                entity: EntityKey {
                    path: "source.py".into(),
                    kind: "function".into(),
                    qualname: Some("target".into()),
                    owner: None,
                    definition_ordinal: 0,
                },
                span,
                entity_span: span,
                fields: PassageFields {
                    identity: "function target".into(),
                    signature: "def target():".into(),
                    documentation: "".into(),
                    body: source.trim_end().into(),
                    path: "source.py".into(),
                },
                source_hash: hash.clone(),
                language: "python".into(),
                role: "definition".into(),
                split_reason: None,
                signals: BTreeMap::new(),
                implementation_start_line: Some(2),
            };
            let tx = db.immediate().unwrap();
            replace_file_passages(&tx, 1, &[passage], Some(&hash), &PassagePolicy::default())
                .unwrap();
            tx.commit().unwrap();
            let spec =
                json!({"model_id":"test/compat","revision":"a".repeat(40),"backend":"provided"});
            let profile =
                RetrievalProfile::from_json(&json!({"identity":spec,"behavior":spec}).to_string())
                    .unwrap();
            db.set_meta(
                "retrieval_profile",
                &serde_json::to_string(&profile).unwrap(),
            )
            .unwrap();
        }
        let legacy: Value = serde_json::from_str(include_str!(
            "../../ken-models/tests/fixtures/profile-identity/linux.json"
        ))
        .unwrap();
        let installation = root.path().join("minimal-resources.json");
        // No grammar declaration, ranking registry or physical model sources are needed by exact evidence.
        std::fs::write(
            &installation,
            json!({"format":"ken-search-installation/1","legacy_runtime":legacy["legacy_runtime"]})
                .to_string(),
        )
        .unwrap();
        Self { root, installation }
    }
    fn run(&self, args: &[&str]) -> Output {
        Command::new(env!("CARGO_BIN_EXE_ken-rs"))
            .arg("--resources")
            .arg(&self.installation)
            .args(args)
            .current_dir(self.root.path())
            .env_clear()
            .env("HOME", self.root.path())
            .env("PATH", "")
            .env("KEN_CONFIG_DIR", self.root.path().join("config"))
            .env("KEN_EMBED_DEVICE", "cpu")
            .output()
            .unwrap()
    }
    fn schemas(&self) -> Value {
        let mut child = Command::new(env!("CARGO_BIN_EXE_ken-rs"))
            .arg("--resources")
            .arg(&self.installation)
            .arg("mcp")
            .arg(self.root.path())
            .current_dir(self.root.path())
            .env_clear()
            .env("HOME", self.root.path())
            .env("PATH", "")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        let mut input = child.stdin.take().unwrap();
        let output = child.stdout.take().unwrap();
        let (tx, rx) = mpsc::channel();
        let reader = thread::spawn(move || {
            for line in BufReader::new(output).lines() {
                let Ok(line) = line else { break };
                if tx.send(line).is_err() {
                    break;
                }
            }
        });
        let observed = (|| -> Result<Value, Box<dyn std::error::Error>> {
            writeln!(
                input,
                "{}",
                json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"search-compat-test","version":"1"}}})
            )?;
            input.flush()?;
            let _: Value = serde_json::from_str(&rx.recv_timeout(Duration::from_secs(8))?)?;
            writeln!(
                input,
                "{}",
                json!({"jsonrpc":"2.0","method":"notifications/initialized"})
            )?;
            writeln!(
                input,
                "{}",
                json!({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}})
            )?;
            input.flush()?;
            let response: Value = serde_json::from_str(&rx.recv_timeout(Duration::from_secs(8))?)?;
            Ok(response["result"]["tools"].clone())
        })();
        drop(input);
        let _ = child.kill();
        let _ = child.wait();
        let _ = reader.join();
        observed.unwrap()
    }
}
fn value(output: Output) -> Value {
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}
#[test]
fn evidence_ordinary_cli_and_tools_share_verified_structure_without_grammar_or_models() {
    let f = Fixture::new(true);
    let ordinary = value(f.run(&[
        "search-symbols",
        "source.py::target",
        "--response-format",
        "evidence",
        "--json",
    ]));
    let tool = value(f.run(&[
        "tools",
        "find",
        "source.py::target",
        "--scope",
        "symbols",
        "--response-format",
        "evidence",
        "--output-format",
        "json",
    ]));
    assert_eq!(ordinary, tool);
    assert_eq!(ordinary["results"][0]["entity"]["qualname"], "target");
    assert_eq!(ordinary["results"][0]["stale"], false);
    assert!(
        ordinary["results"][0]["evidence"][0]["content"]
            .as_str()
            .unwrap()
            .contains("verified 🦀")
    );
    assert_eq!(ordinary["results"][0]["evidence"][0]["start_line"], 1);
    assert_eq!(ordinary["results"][0]["evidence"][0]["end_line"], 2);
    assert_eq!(
        ordinary,
        value(f.run(&[
            "tools",
            "find",
            "source.py::target",
            "--scope",
            "symbols",
            "--response-format",
            "evidence"
        ]))
    );
    let text = f.run(&[
        "search-symbols",
        "source.py::target",
        "--response-format",
        "evidence",
    ]);
    assert!(text.status.success());
    let text = String::from_utf8(text.stdout).unwrap();
    assert!(text.contains("source.py:1-2 :: target"));
    assert!(text.contains("2 |     return 'verified 🦀'"));
    assert!(!text.contains("ranking_score"));
    assert!(!f.root.path().join("cache").exists());
    assert!(!f.root.path().join("private").exists());
}
#[test]
fn missing_prepared_index_has_original_retrieval_error_code_and_cli_exit_one() {
    let f = Fixture::new(false);
    std::fs::remove_file(&f.installation).unwrap();
    let output = f.run(&[
        "search-files",
        "find source",
        "--response-format",
        "evidence",
        "--json",
    ]);
    assert_eq!(output.status.code(), Some(1));
    assert!(
        output.stderr.is_empty(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let v: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(v["ok"], false);
    assert_eq!(v["code"], "retrieval_index_required");
    assert_eq!(v["results"], json!([]));
    assert!(
        v["next_action"]
            .as_str()
            .unwrap()
            .contains("ken retrieval index")
    );
    let output = f.run(&[
        "search-files",
        "find source",
        "--response-format",
        "evidence",
    ]);
    assert_eq!(output.status.code(), Some(1));
    assert!(
        String::from_utf8(output.stdout)
            .unwrap()
            .contains("ken retrieval index")
    );
}
#[test]
fn evidence_budget_and_stale_reporting_are_preserved_through_actual_cli() {
    let f = Fixture::new(true);
    let short = value(f.run(&[
        "search-symbols",
        "source.py::target",
        "--response-format",
        "evidence",
        "--max-chars",
        "300",
        "--json",
    ]));
    assert_eq!(short["results"], json!([]));
    assert_eq!(short["truncated"], true);
    assert_eq!(short["omitted_count"], 1);
    std::fs::write(f.root.path().join("source.py"), "replacement source\n").unwrap();
    let stale = value(f.run(&[
        "search-symbols",
        "source.py::target",
        "--response-format",
        "evidence",
        "--json",
    ]));
    assert_eq!(stale["results"][0]["stale"], true);
    assert_eq!(stale["results"][0]["evidence"], json!([]));
    assert!(!stale["warnings"].as_array().unwrap().is_empty());
}
#[test]
fn compatibility_option_errors_precede_model_access_and_old_default_boundaries_remain() {
    let f = Fixture::new(true);
    for (args, message) in [
        (
            vec![
                "search-files",
                "q",
                "--response-format",
                "legacy",
                "--purpose",
                "tests",
            ],
            "--purpose requires --response-format evidence or compact",
        ),
        (
            vec![
                "search-files",
                "q",
                "--response-format",
                "evidence",
                "--piece-kind",
                "file",
            ],
            "--piece-kind requires the default or compact response mode",
        ),
        (
            vec![
                "search-files",
                "q",
                "--response-format",
                "compact",
                "--json",
            ],
            "compact is text",
        ),
    ] {
        let output = f.run(&args);
        assert_eq!(output.status.code(), Some(1));
        assert!(output.stdout.is_empty());
        assert!(String::from_utf8_lossy(&output.stderr).contains(message));
    }
    let output = f.run(&[
        "tools",
        "find",
        "target",
        "--scope",
        "text",
        "--response-format",
        "evidence",
    ]);
    assert_eq!(output.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&output.stderr).contains("files or symbols"));
}
#[test]
fn legacy_mode_reaches_focused_selected_model_and_evidence_is_advertised_in_schema() {
    let f = Fixture::new(true);
    std::fs::remove_file(&f.installation).unwrap();
    let output = f.run(&[
        "search-symbols",
        "target",
        "--response-format",
        "legacy",
        "--json",
    ]);
    assert_eq!(output.status.code(), Some(1));
    let error = String::from_utf8_lossy(&output.stderr);
    assert!(error.contains("minimal-resources.json"), "{error}");
    assert!(!error.contains("compatibility response mode"));
    let list = f.schemas();
    let find = list
        .as_array()
        .unwrap()
        .iter()
        .find(|t| t["name"] == "ken_find")
        .unwrap();
    assert!(
        find["inputSchema"]["properties"]["response_format"]["enum"]
            .as_array()
            .unwrap()
            .contains(&json!("evidence"))
    );
}
