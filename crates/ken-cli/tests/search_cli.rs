#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
use flate2::read::GzDecoder;
use ken_core::project::{DiscoveryContext, ProjectPaths};
use ken_index::{IndexOptions, Indexer};
use ken_retrieval::PassagePolicy;
use ken_store::ProjectDatabase;
use ken_syntax::{GrammarCatalog, ParserRegistry};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    fs,
    io::Read,
    path::{Path, PathBuf},
    process::{Command, Output, Stdio},
};

#[path = "support/public_evidence.rs"]
mod evidence;

fn original() -> Value {
    let mut raw = String::new();
    GzDecoder::new(
        &include_bytes!("../../ken-retrieval/tests/fixtures/best-search-reference.json.gz")[..],
    )
    .read_to_string(&mut raw)
    .unwrap();
    let corpus: Value = serde_json::from_str(&raw).unwrap();
    corpus["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|r| r["id"] == "registered-symbol")
        .unwrap()
        .clone()
}
struct Fixture {
    directory: tempfile::TempDir,
    installation: PathBuf,
    project: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        let directory = tempfile::tempdir().unwrap();
        let root = directory.path();
        let project = root.join("project");
        fs::create_dir_all(project.join(".ken")).unwrap();
        fs::write(
            project.join(".ken/meta.json"),
            r#"{"project_id":{"name":"public-transport"}}"#,
        )
        .unwrap();
        let mut db = ProjectDatabase::open(&project.join(".ken/ken.db")).unwrap();
        db.initialize().unwrap();
        fs::create_dir(root.join("grammars")).unwrap();
        fs::copy(
            std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
            root.join("grammars/manifest.json"),
        )
        .unwrap();
        let installation = root.join("installation.json");
        fs::write(&installation,json!({"format":"ken-search-installation/1","grammar_manifest":"grammars/manifest.json","ranking_directory":"missing-ranks","private_parent":"owned","cache_parent":"cache","bundled_npz":"unused.npz","sources":{},"acquisition":"offline","legacy_runtime":original()["input"]["models"]["legacy_runtime"],"onnx_library":null,"translation":null}).to_string()).unwrap();
        Self {
            directory,
            installation,
            project,
        }
    }
    fn invoke(&self, path: &Path, args: &[String]) -> Output {
        let mut command = Command::new(evidence::native());
        evidence::application_environment(&mut command);
        command
            .arg("--resources")
            .arg(&self.installation)
            .args(args)
            .arg("--path")
            .arg(path)
            .current_dir(self.directory.path())
            .env("HOME", self.directory.path().join("home"))
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let child = command.spawn().unwrap();
        let retained = evidence::start(child.id(), &command, &self.installation, path);
        let output = child.wait_with_output().unwrap();
        if let Some(root) = retained {
            fs::write(root.join("stdout"), &output.stdout).unwrap();
            fs::write(root.join("stderr"), &output.stderr).unwrap();
            fs::write(root.join("exit"), output.status.code().unwrap().to_string()).unwrap();
            fs::write(root.join("stdin"), b"").unwrap();
        }
        output
    }
    fn index(&self, files: &Value) {
        let paths = ProjectPaths::at(
            &self.project,
            &DiscoveryContext {
                cwd: self.project.clone(),
                forced_root: None,
                home: None,
            },
        )
        .unwrap();
        let mut db = ProjectDatabase::open(&paths.db()).unwrap();
        let mut names = Vec::new();
        for (name, text) in files.as_object().unwrap() {
            let path = self.project.join(name);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, text.as_str().unwrap()).unwrap();
            names.push(name.into());
        }
        let registry = ParserRegistry::new(
            GrammarCatalog::prepared(&PathBuf::from(
                std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap(),
            ))
            .unwrap(),
        );
        Indexer::new(&registry)
            .index_files(
                &mut db,
                &paths,
                &names,
                &IndexOptions {
                    retrieval_policy: Some(PassagePolicy::default()),
                    ..Default::default()
                },
                &mut |_: &str, _: &str| {},
            )
            .unwrap();
    }
}

#[test]
fn actual_cli_preserves_original_empty_missing_and_argument_boundaries() {
    let bytes = include_bytes!("fixtures/search-boundary-reference-v2.json.gz");
    assert_eq!(bytes.len(), 2361);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "856d34b5a0868185cde06912a4634a6abf8275fb3aeae3589d4b68fe603e2ed6"
    );
    let mut raw = String::new();
    GzDecoder::new(&bytes[..]).read_to_string(&mut raw).unwrap();
    let corpus: Value = serde_json::from_str(&raw).unwrap();
    assert_eq!(corpus["format"], "ken-search-cli-original/1");
    assert_eq!(corpus["rows"].as_array().unwrap().len(), 15);
    let fixture = Fixture::new();
    let missing = fixture.directory.path().join("missing");
    fs::create_dir(&missing).unwrap();
    for row in corpus["rows"].as_array().unwrap() {
        let path = if row["indexed"] == true {
            &fixture.project
        } else {
            &missing
        };
        let args: Vec<String> = serde_json::from_value(row["args"].clone()).unwrap();
        let got = fixture.invoke(path, &args);
        assert_eq!(
            got.status.code(),
            Some(row["exit"].as_i64().unwrap() as i32),
            "{}: {}",
            row["id"],
            String::from_utf8_lossy(&got.stderr)
        );
        if row["comparison"] == "streams" {
            let stdout = String::from_utf8(got.stdout).unwrap();
            let expected = row["stdout"].as_str().unwrap();
            if expected.starts_with('{') {
                assert_eq!(
                    serde_json::from_str::<Value>(&stdout).unwrap(),
                    serde_json::from_str::<Value>(expected).unwrap(),
                    "{}",
                    row["id"]
                );
            } else {
                assert_eq!(stdout, expected, "{}", row["id"]);
            }
            assert_eq!(
                String::from_utf8(got.stderr).unwrap(),
                row["stderr"]
                    .as_str()
                    .unwrap()
                    .replace("PROJECT", path.to_str().unwrap()),
                "{}",
                row["id"]
            );
        } else {
            assert!(got.stdout.is_empty(), "{}", row["id"]);
            assert!(!got.stderr.is_empty(), "{}", row["id"]);
        }
    }
    assert!(!missing.join(".ken").exists());
    assert!(!fixture.directory.path().join("cache").exists());
    for mode in ["evidence", "legacy"] {
        let args =
            ["search-symbols", "find", "value", "--response-format", mode].map(str::to_owned);
        let result = fixture.invoke(&fixture.project, &args);
        assert_eq!(result.status.code(), Some(1));
        assert!(result.stdout.is_empty());
        assert!(
            String::from_utf8(result.stderr)
                .unwrap()
                .contains("not available in the native command yet")
        );
    }
}

#[test]
fn default_compact_and_json_search_quote_current_source_without_model_resources() {
    let fixture = Fixture::new();
    fixture
        .index(&json!({"source.py":"def public_transport_unique(value):\n    return value + 3\n"}));
    let args = |items: &[&str]| items.iter().map(|s| s.to_string()).collect::<Vec<_>>();
    for extra in [vec![], vec!["--response-format", "compact"]] {
        let mut input = vec!["search-symbols", "public_transport_unique"];
        input.extend(extra);
        let out = fixture.invoke(&fixture.project, &args(&input));
        assert!(
            out.status.success(),
            "{}",
            String::from_utf8_lossy(&out.stderr)
        );
        assert!(out.stderr.is_empty());
        assert_eq!(out.stdout,b"source.py:1-2 :: public_transport_unique\n1 | def public_transport_unique(value):\n2 |     return value + 3\n");
    }
    let out = fixture.invoke(
        &fixture.project,
        &args(&["search-symbols", "public_transport_unique", "--json"]),
    );
    assert!(out.status.success());
    assert!(out.stderr.is_empty());
    let value: Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(value["query"], "public_transport_unique");
    assert_eq!(
        value["results"][0]["entity"]["qualname"],
        "public_transport_unique"
    );
    assert_eq!(value["profile_version"], "best-exact-source-v1");
    assert!(!fixture.directory.path().join("cache").exists());
    assert!(!fixture.directory.path().join("owned").exists());
}

#[path = "../../ken-search/tests/support/search_response.rs"]
mod response;
#[test]
fn compact_tool_cli_encodes_compact_search_as_a_json_string() {
    let fixture = Fixture::new();
    fixture
        .index(&json!({"source.py":"def public_transport_unique(value):\n    return value + 3\n"}));
    let args = [
        "tools",
        "--compact",
        "find",
        "public_transport_unique",
        "--scope",
        "symbols",
        "--response-format",
        "compact",
    ]
    .map(str::to_owned);
    let output = fixture.invoke(&fixture.project, &args);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stderr.is_empty());
    let source: String = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(
        source,
        "source.py:1-2 :: public_transport_unique\n1 | def public_transport_unique(value):\n2 |     return value + 3"
    );
    assert_eq!(String::from_utf8(output.stdout).unwrap().lines().count(), 1);
}
fn configure_registered(fixture: &Fixture) {
    let mut config: Value =
        serde_json::from_slice(&fs::read(&fixture.installation).unwrap()).unwrap();
    config["ranking_directory"] = json!(
        std::env::var_os("KEN_PUBLIC_RANKS")
            .map(PathBuf::from)
            .unwrap_or_else(
                || Path::new(env!("CARGO_MANIFEST_DIR")).join("../ken-retrieval/resources/ranking")
            )
    );
    config["onnx_library"] = json!(PathBuf::from(std::env::var_os("KEN_ORT_LIBRARY").unwrap()));
    let runtime: Value = serde_json::from_slice(
        &fs::read(std::env::var_os("KEN_CT2_PREPARATION").unwrap()).unwrap(),
    )
    .unwrap();
    config["translation"] = json!({"registration":runtime["registration"],"module_path":runtime["module_path"],"core_root":runtime["core_root"]});
    for (model, variable) in [
        ("minishlab/potion-code-16M-v2", "KEN_POTION_SOURCE"),
        ("mrsladoje/CodeRankEmbed-onnx-int8", "KEN_CONTEXT_SNAPSHOT"),
        ("cross-encoder/ettin-reranker-68m-v1", "KEN_ETTIN_SOURCE"),
        ("Prukario/opus-mt-es-en-ct2-int8", "KEN_TRANSLATION_SOURCE"),
    ] {
        config["sources"][model] = json!(PathBuf::from(std::env::var_os(variable).unwrap()));
    }
    fs::write(&fixture.installation, config.to_string()).unwrap();
}
#[test]
fn actual_registered_cli_runs_native_models_and_matches_original_response() {
    let fixture = Fixture::new();
    let reference = original();
    fixture.index(&reference["input"]["projects"][0]["files"]);
    configure_registered(&fixture);
    let args = [
        "search-symbols",
        "Preserve",
        "the",
        "exception",
        "cause",
        "--limit",
        "1",
        "--piece-kind",
        "symbol",
        "--json",
    ]
    .map(str::to_owned);
    let got = fixture.invoke(&fixture.project, &args);
    assert!(
        got.status.success(),
        "{}",
        String::from_utf8_lossy(&got.stderr)
    );
    assert!(got.stderr.is_empty());
    let actual: Value = serde_json::from_slice(&got.stdout).unwrap();
    response::real_response(&actual, &reference["events"][1]["result"], "CLI original");
    assert!(fixture.directory.path().join("owned").is_dir());
}

#[path = "support/mcp_cases.rs"]
mod mcp;
