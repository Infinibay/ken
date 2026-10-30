//! Original accepted CLI forms reach real native owners without model inference.
use serde_json::{Value, json};
use std::{
    fs,
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Output, Stdio},
    thread,
    time::{Duration, Instant},
};

struct Fixture {
    root: tempfile::TempDir,
    deployment: tempfile::TempDir,
    resources: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let deployment = tempfile::tempdir().unwrap();
        fs::create_dir(root.path().join(".ken")).unwrap();
        fs::write(
            root.path().join(".ken/meta.json"),
            json!({"project_id":"cli-compatibility","auth_token":"compat-token"}).to_string(),
        )
        .unwrap();
        let mut db = ken_store::ProjectDatabase::open(&root.path().join(".ken/ken.db")).unwrap();
        db.initialize().unwrap();
        let legacy: Value = serde_json::from_str(include_str!(
            "../../ken-models/tests/fixtures/profile-identity/linux.json"
        ))
        .unwrap();
        let resources = deployment.path().join("resources.json");
        fs::write(&resources,json!({"format":"ken-search-installation/1","grammar_manifest":PathBuf::from(std::env::var_os("KEN_GRAMMAR_MANIFEST").expect("prepared native grammars")),"ranking_directory":"absent-ranks","private_parent":"private","cache_parent":"cache","bundled_npz":"absent-static.npz","sources":{},"acquisition":"offline","legacy_runtime":legacy["legacy_runtime"]}).to_string()).unwrap();
        Self {
            root,
            deployment,
            resources,
        }
    }
    fn command(&self) -> Command {
        let mut command = Command::new(env!("CARGO_BIN_EXE_ken-rs"));
        command
            .arg("--resources")
            .arg(&self.resources)
            .current_dir(self.root.path())
            .env_clear()
            .env("HOME", self.root.path())
            .env("PATH", "")
            .env("KEN_CONFIG_DIR", self.deployment.path().join("config"))
            .env("KEN_EMBED_DEVICE", "cpu");
        command
    }
    fn run(&self, args: &[&str]) -> Output {
        let streams = tempfile::tempdir().unwrap();
        let stdout = streams.path().join("stdout");
        let stderr = streams.path().join("stderr");
        let mut command = self.command();
        command
            .args(args)
            .stdin(Stdio::null())
            .stdout(fs::File::create(&stdout).unwrap())
            .stderr(fs::File::create(&stderr).unwrap());
        let mut child = OwnedChild(command.spawn().unwrap());
        let status = child.wait(Duration::from_secs(45));
        Output {
            status,
            stdout: fs::read(stdout).unwrap(),
            stderr: fs::read(stderr).unwrap(),
        }
    }
    fn tool(&self, args: &[&str]) -> Value {
        let args = std::iter::once("tools")
            .chain(std::iter::once("--json"))
            .chain(args.iter().copied())
            .collect::<Vec<_>>();
        value(self.run(&args))
    }
}
struct OwnedChild(Child);
impl OwnedChild {
    fn wait(&mut self, budget: Duration) -> std::process::ExitStatus {
        let deadline = Instant::now() + budget;
        loop {
            if let Some(status) = self.0.try_wait().unwrap() {
                return status;
            }
            assert!(
                Instant::now() < deadline,
                "native child exceeded bounded lifecycle deadline"
            );
            thread::sleep(Duration::from_millis(10));
        }
    }
}
impl Drop for OwnedChild {
    fn drop(&mut self) {
        if self.0.try_wait().ok().flatten().is_none() {
            let _ = self.0.kill();
        }
        let _ = self.0.wait();
    }
}
fn value(output: Output) -> Value {
    assert!(
        output.status.success(),
        "exit={:?} stderr={}",
        output.status.code(),
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}
fn atom(predicate: &str, subject: &str, object: &str) -> String {
    json!({"predicate":predicate,"subject":subject,"object":object}).to_string()
}

#[test]
fn optional_find_query_flag_and_existing_positional_both_reach_live_text_search() {
    let f = Fixture::new();
    fs::write(f.root.path().join("code.py"), "TOKEN = 'native_needle'\n").unwrap();
    let positional = f.tool(&["find", "native_needle", "--scope", "text", "--literal"]);
    assert_eq!(positional["mode"], "literal");
    let flagged = f.tool(&[
        "find",
        "--query",
        "native_needle",
        "--scope",
        "text",
        "--literal",
    ]);
    assert_eq!(flagged, positional);
    let alias = f.tool(&[
        "ken_find",
        "--query",
        "native_needle",
        "--scope",
        "text",
        "--literal",
    ]);
    assert_eq!(alias, positional);
}
#[test]
fn who_negative_boolean_reaches_domain_admission_without_loading_a_model() {
    let f = Fixture::new();
    let output = f.run(&[
        "tools",
        "who",
        "responsibility",
        "--no-verify",
        "--limit",
        "0",
        "--output-format",
        "json",
    ]);
    assert_eq!(output.status.code(), Some(1));
    let error = String::from_utf8_lossy(&output.stderr);
    assert!(error.contains("limit must be 1..10"), "{error}");
    assert!(!error.contains("unexpected argument"));
    assert!(!f.deployment.path().join("private").exists());
}
#[test]
fn standalone_rule_boolean_flags_enable_and_disable_automatic_execution_on_a_validated_contract() {
    let f = Fixture::new();
    let definition=json!({"id":"cli.boolean","description":"A class exists in the explicit source fixture.","expectation":"some_match","query":"language \"kql/2\";module cli_boolean;query q{class $c {} select $c.name;}","examples":[{"name":"has class","files":{"example.py":"class Ready: pass\n"},"expect":"pass"},{"name":"no class","files":{"example.py":"value = 1\n"},"expect":"fail"}]}).to_string();
    assert_eq!(
        f.tool(&["rule", "--action", "create", "--definition", &definition])["state"],
        "draft"
    );
    assert_eq!(
        f.tool(&["rule", "--action", "validate", "--rule-id", "cli.boolean"])["state"],
        "validated"
    );
    let enabled = f.tool(&[
        "rule",
        "--action",
        "enable",
        "--rule-id",
        "cli.boolean",
        "--automatic",
    ]);
    assert_eq!(enabled["state"], "enabled");
    assert_eq!(enabled["automatic"], true);
    let manual = f.tool(&[
        "ken_rule",
        "--action",
        "enable",
        "--rule-id",
        "cli.boolean",
        "--no-automatic",
    ]);
    assert_eq!(manual["state"], "enabled");
    assert_eq!(manual["automatic"], false);
    assert_eq!(
        f.tool(&["rule", "--action", "show", "--rule-id", "cli.boolean"])["automatic"],
        false
    );
}
#[test]
fn spaced_fact_objects_persist_as_one_native_bundle_and_existing_json_array_form_stays_usable() {
    let f = Fixture::new();
    let first = atom("owns", "store", "writes");
    let second = atom("owns", "store", "reads");
    assert_eq!(
        f.tool(&["reason-record", "cli-facts", "--facts", &first, &second])["changed"],
        true
    );
    for goal in [&first, &second] {
        assert_eq!(
            f.tool(&["reason", "Which capability?", "--goal", goal])["status"],
            "supported"
        );
    }
    let third = atom("owns", "store", "reviews");
    let array = format!("[{third}]");
    assert_eq!(
        f.tool(&["reason-record", "native-array-form", "--facts", &array])["changed"],
        true
    );
    assert_eq!(
        f.tool(&["reason", "Which capability?", "--goal", &third])["status"],
        "supported"
    );
    f.tool(&["reason-record", "cli-facts", "--retract"]);
    assert_eq!(
        f.tool(&["reason", "Which capability?", "--goal", &first])["status"],
        "unknown"
    );
}
#[test]
fn spaced_rule_objects_drive_native_inference_instead_of_becoming_one_object_argument() {
    let f = Fixture::new();
    let facts=json!([{"predicate":"owns","subject":"store","object":"writes"},{"predicate":"owns","subject":"store","object":"reads"}]).to_string();
    f.tool(&["reason-record", "premises", "--facts", &facts]);
    let rule = |object: &str| {
        json!({"body":[{"predicate":"owns","subject":"?x","object":object}],"head":{"predicate":"capable","subject":"?x","object":object}}).to_string()
    };
    let first = rule("writes");
    let second = rule("reads");
    assert_eq!(
        f.tool(&["reason-record", "cli-rules", "--rules", &first, &second])["changed"],
        true
    );
    for object in ["writes", "reads"] {
        let goal = atom("capable", "store", object);
        assert_eq!(
            f.tool(&["reason", "What follows?", "--goal", &goal])["status"],
            "supported"
        );
    }
}
#[test]
fn spaced_assumption_objects_are_conditional_and_do_not_persist_into_later_cli_calls() {
    let f = Fixture::new();
    let first = atom("provisional", "store", "fast");
    let second = atom("provisional", "store", "auditable");
    let assumed = f.tool(&[
        "reason",
        "Under these conditions?",
        "--goal",
        &first,
        "--assumptions",
        &first,
        &second,
    ]);
    assert_eq!(assumed["status"], "supported");
    assert_eq!(
        f.tool(&["reason", "Without those conditions?", "--goal", &first])["status"],
        "unknown"
    );
    assert_eq!(
        f.tool(&["reason", "Without those conditions?", "--goal", &second])["status"],
        "unknown"
    );
}
fn http(port: u16, method: &str, path: &str, body: &Value) -> std::io::Result<(u16, Value)> {
    let address: SocketAddr = format!("127.0.0.1:{port}").parse().unwrap();
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_millis(250))?;
    stream.set_read_timeout(Some(Duration::from_secs(2)))?;
    stream.set_write_timeout(Some(Duration::from_secs(2)))?;
    let data = if method == "GET" {
        String::new()
    } else {
        body.to_string()
    };
    write!(
        stream,
        "{method} {path} HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer compat-token\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{data}",
        data.len()
    )?;
    stream.flush()?;
    let mut bytes = String::new();
    stream.read_to_string(&mut bytes)?;
    let (head, body) = bytes
        .split_once("\r\n\r\n")
        .ok_or_else(|| std::io::Error::other("missing HTTP header"))?;
    let status = head
        .split_whitespace()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .ok_or_else(|| std::io::Error::other("missing HTTP status"))?;
    let value = serde_json::from_str(body).map_err(std::io::Error::other)?;
    Ok((status, value))
}
fn ready(child: &mut OwnedChild, root: &Path) -> u16 {
    let deadline = Instant::now() + Duration::from_secs(8);
    loop {
        assert!(
            child.0.try_wait().unwrap().is_none(),
            "serve exited instead of remaining the foreground process"
        );
        if let Ok(port) = fs::read_to_string(root.join(".ken/daemon.port"))
            && let Ok(port) = port.trim().parse()
            && http(port, "GET", "/health", &Value::Null).is_ok_and(|(status, _)| status == 200)
        {
            return port;
        }
        assert!(
            Instant::now() < deadline,
            "native daemon never published healthy runtime files"
        );
        thread::sleep(Duration::from_millis(10));
    }
}
#[test]
fn direct_serve_background_redirects_diagnostics_but_remains_the_serving_process() {
    for background in [false, true] {
        let f = Fixture::new();
        let stderr = f.deployment.path().join("caller-stderr");
        let mut command = f.command();
        command.arg("serve").arg(f.root.path());
        if background {
            command.arg("--background");
        }
        command
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(fs::File::create(&stderr).unwrap());
        let mut child = OwnedChild(command.spawn().unwrap());
        let port = ready(&mut child, f.root.path());
        // A malformed typed field reaches the real handler's diagnostic path without
        // querying an encoder, changing fixtures or relying on startup timing.
        assert_eq!(
            http(port, "POST", "/sessions/start", &json!({"session_id":[]}))
                .unwrap()
                .0,
            500
        );
        assert!(child.0.try_wait().unwrap().is_none());
        assert_eq!(http(port, "POST", "/shutdown", &json!({})).unwrap().0, 200);
        assert!(child.wait(Duration::from_secs(8)).success());
        let caller = fs::read_to_string(&stderr).unwrap();
        let logfile = f.root.path().join(".ken/daemon.log");
        let logged = fs::read_to_string(logfile).unwrap_or_default();
        if background {
            assert!(
                logged.contains("ken handler failed:"),
                "background diagnostics missing from daemon.log; caller={caller}"
            );
            assert!(!caller.contains("ken handler failed:"));
        } else {
            assert!(
                caller.contains("ken handler failed:"),
                "foreground diagnostics missing from stderr: {caller}"
            );
            assert!(!logged.contains("ken handler failed:"));
        }
        assert!(
            !f.deployment.path().join("private").exists(),
            "no model inference or preparation is needed"
        );
    }
}
#[test]
fn legacy_test_discovery_retains_the_original_structured_response_without_an_output_override() {
    let f = Fixture::new();
    fs::write(f.root.path().join("code.py"), "value = 1\n").unwrap();
    fs::create_dir(f.root.path().join("tests")).unwrap();
    fs::write(
        f.root.path().join("tests/test_code.py"),
        "def test_code(): pass\n",
    )
    .unwrap();
    let db = rusqlite::Connection::open(f.root.path().join(".ken/ken.db")).unwrap();
    for path in ["code.py", "tests/test_code.py"] {
        db.execute("INSERT INTO ci_files(path,language,content_hash,mtime,indexed_at)VALUES(?,'python',x'00',0,0)",[path]).unwrap();
    }
    drop(db);
    let result = value(f.run(&[
        "tools",
        "find",
        "code.py",
        "--scope",
        "tests",
        "--response-format",
        "legacy",
    ]));
    assert_eq!(result["ok"], true);
    assert_eq!(result["path"], "code.py");
    assert_eq!(result["tests"][0]["path"], "tests/test_code.py");
    assert_eq!(result["tests"][0]["reason"], "named for target");
    assert_eq!(result, f.tool(&["find", "code.py", "--scope", "tests"]));
}
#[test]
fn legacy_intent_without_prompt_history_stays_structured_and_needs_no_model() {
    let f = Fixture::new();
    let result = value(f.run(&[
        "tools",
        "find",
        "familiar task",
        "--scope",
        "intent",
        "--response-format",
        "legacy",
    ]));
    assert_eq!(
        result,
        json!({"ok":true,"query":"familiar task","files":[],"note":"no embedded prompt history yet"})
    );
    assert!(!f.deployment.path().join("private").exists());
}
#[test]
fn legacy_structural_search_preserves_data_while_default_compact_remains_text() {
    let f = Fixture::new();
    fs::write(f.root.path().join("code.py"), "class Visible: pass\n").unwrap();
    let query = "require $x ENTITY CLASS";
    let legacy = value(f.run(&[
        "tools",
        "find",
        query,
        "--scope",
        "structure",
        "--source-path",
        "code.py",
        "--cache-mb",
        "0",
        "--response-format",
        "legacy",
    ]));
    assert_eq!(legacy["matches"].as_array().unwrap().len(), 1);
    let structured = f.tool(&[
        "find",
        query,
        "--scope",
        "structure",
        "--source-path",
        "code.py",
        "--cache-mb",
        "0",
    ]);
    assert_eq!(legacy["matches"], structured["matches"]);
    let compact = f.run(&[
        "tools",
        "find",
        query,
        "--scope",
        "structure",
        "--source-path",
        "code.py",
        "--cache-mb",
        "0",
    ]);
    assert!(
        compact.status.success(),
        "{}",
        String::from_utf8_lossy(&compact.stderr)
    );
    assert!(serde_json::from_slice::<Value>(&compact.stdout).is_err());
    assert!(String::from_utf8_lossy(&compact.stdout).contains("code.py"));
}
#[test]
fn tool_source_path_after_the_tool_name_is_distinct_from_project_path_before_it() {
    let f = Fixture::new();
    fs::write(f.root.path().join("inside.py"), "class Inside: pass\n").unwrap();
    fs::write(f.root.path().join("outside.py"), "class Outside: pass\n").unwrap();
    let root = f.root.path().to_str().unwrap();
    let result = value(f.run(&[
        "tools",
        "--path",
        root,
        "find",
        "require $x ENTITY CLASS",
        "--scope",
        "structure",
        "--path",
        "inside.py",
        "--cache-mb",
        "0",
        "--output-format",
        "json",
    ]));
    assert_eq!(result["matches"].as_array().unwrap().len(), 1);
    let alias = f.tool(&[
        "find",
        "require $x ENTITY CLASS",
        "--scope",
        "structure",
        "--source-path",
        "inside.py",
        "--cache-mb",
        "0",
    ]);
    assert_eq!(alias["matches"], result["matches"]);
}
#[test]
fn kql2_compact_formats_real_rows_and_outer_json_still_overrides_presentation() {
    let f = Fixture::new();
    fs::write(f.root.path().join("code.py"), "class Visible: pass\n").unwrap();
    let query = "language \"kql/2\";module compact_cli;query q{class $c {} select $c.name;}";
    let data = f.tool(&[
        "find",
        query,
        "--scope",
        "structure",
        "--query-language",
        "kql/2",
        "--source-path",
        "code.py",
        "--cache-mb",
        "0",
        "--output-format",
        "compact",
    ]);
    assert_eq!(data["rows"], json!([["Visible"]]));
    let column = data["columns"][0].as_str().unwrap();
    let compact = f.run(&[
        "tools",
        "find",
        query,
        "--scope",
        "structure",
        "--query-language",
        "kql/2",
        "--source-path",
        "code.py",
        "--cache-mb",
        "0",
        "--output-format",
        "compact",
    ]);
    assert!(
        compact.status.success(),
        "{}",
        String::from_utf8_lossy(&compact.stderr)
    );
    let text = String::from_utf8(compact.stdout).unwrap();
    assert!(
        serde_json::from_str::<Value>(&text).is_err(),
        "compact must be text: {text}"
    );
    assert!(text.contains("row 1:"), "{text}");
    assert!(text.contains(&format!("  {column}: Visible")), "{text}");
    assert!(text.contains("complete: true"));
}
#[test]
fn check_and_rule_compact_modes_keep_status_but_remove_original_expandable_check_fields() {
    let f = Fixture::new();
    let list = f.run(&[
        "tools",
        "rule",
        "--action",
        "list",
        "--output-format",
        "compact",
    ]);
    assert!(
        list.status.success(),
        "{}",
        String::from_utf8_lossy(&list.stderr)
    );
    assert_eq!(String::from_utf8(list.stdout).unwrap(), "No results.\n");
    assert_eq!(f.tool(&["rule", "--action", "list"]), json!({"rules":[]}));
    // Empty not_applicable checks intentionally have no historical receipt.
    // Explicit rule selection executes a check and creates a real saved receipt.
    let definition = json!({
        "id":"cli.compact",
        "description":"Preserve the historical compact receipt contract.",
        "query":"language \"kql/2\";module cli_compact;query q{class $c {} select $c.name;}"
    })
    .to_string();
    assert_eq!(
        f.tool(&["rule", "--action", "create", "--definition", &definition])["state"],
        "draft"
    );
    let report = f.tool(&["check", "--rules", "cli.compact"]);
    assert_eq!(report["checks"].as_array().unwrap().len(), 1);
    let id = report["run_id"].as_str().unwrap();
    let compact = f.run(&[
        "tools",
        "check",
        "--run-id",
        id,
        "--output-format",
        "compact",
    ]);
    assert!(
        compact.status.success(),
        "{}",
        String::from_utf8_lossy(&compact.stderr)
    );
    let text = String::from_utf8(compact.stdout).unwrap();
    assert!(serde_json::from_str::<Value>(&text).is_err(), "{text}");
    assert!(text.contains(&format!("run_id: {id}")));
    assert!(text.contains("status:"));
    for omitted in ["created_at:", "claim:", "scope: project", "selection: ."] {
        assert!(!text.contains(omitted), "{text}");
    }
    let json = f.tool(&["check", "--run-id", id, "--output-format", "compact"]);
    assert_eq!(json["run_id"], id);
    assert!(json.get("created_at").is_some());
    assert!(json.get("claim").is_some());
}
#[test]
fn model_json_retains_original_backend_labels_and_multilingual_metadata_without_assets() {
    let f = Fixture::new();
    let data = value(f.run(&["models", "--json"]));
    let rows = data["models"].as_array().unwrap();
    for (name, backend, multilingual) in [
        ("BAAI/bge-base-en", "fastembed", false),
        ("intfloat/multilingual-e5-large", "fastembed", true),
        ("Qwen/Qwen3-Embedding-0.6B", "torch", true),
        ("BAAI/bge-m3", "torch", true),
    ] {
        let row = rows
            .iter()
            .find(|row| row["model"] == name)
            .unwrap_or_else(|| panic!("missing original public catalogue row {name}"));
        assert_eq!(row["backend"], backend, "{name}");
        assert_eq!(row["multilingual"], multilingual, "{name}");
        assert!(row["dim"].as_u64().is_some_and(|n| n > 0));
        assert!(row["mb"].is_number());
    }
    assert!(!f.deployment.path().join("private").exists());
    assert!(!f.deployment.path().join("cache").exists());
}
#[test]
fn generic_tool_flag_families_preserve_boolean_order_and_explicit_empty_arrays() {
    use ken_cli::args::{Command as PublicCommand, ToolCommand};
    let parse = |args: &[&str]| {
        let invocation = ken_cli::args::parse_command_from(
            std::iter::once("ken-rs")
                .chain(args.iter().copied())
                .map(std::ffi::OsString::from),
        )
        .unwrap();
        let PublicCommand::Tools(args) = invocation.command else {
            panic!("expected tools")
        };
        args.command.unwrap()
    };
    for (args, expected) in [
        (
            vec!["tools", "find", "positional", "--query", "named"],
            "named",
        ),
        (
            vec!["tools", "find", "--query", "named", "positional"],
            "positional",
        ),
    ] {
        let ToolCommand::Find(args) = parse(&args) else {
            panic!("expected find")
        };
        assert_eq!(args.query_flag.or(args.query).as_deref(), Some(expected));
    }
    for (args, present) in [
        (vec!["tools", "reason-record", "source"], false),
        (
            vec!["tools", "reason-record", "source", "--facts", "--rules"],
            true,
        ),
    ] {
        let ToolCommand::Knowledge(command) = parse(&args) else {
            panic!("expected knowledge")
        };
        let (_, request) = command.request().unwrap();
        for key in ["facts", "rules"] {
            assert_eq!(
                &request[key],
                &if present { json!([]) } else { Value::Null }
            );
        }
    }
    for (args, present) in [
        (vec!["tools", "find", "q"], false),
        (
            vec![
                "tools",
                "find",
                "q",
                "--rules",
                "--collections",
                "--tags",
                "--rule-files",
            ],
            true,
        ),
    ] {
        let ToolCommand::Find(args) = parse(&args) else {
            panic!("expected find")
        };
        for values in [args.rules, args.collections, args.tags, args.rule_files] {
            assert_eq!(values.is_some(), present);
            if let Some(values) = values {
                assert!(values.is_empty());
            }
        }
    }
    let ToolCommand::Read(read) = parse(&["tools", "read", "code.py", "--include"]) else {
        panic!("expected read")
    };
    assert_eq!(read.include, Some(vec![]));
    let ToolCommand::Check(check) = parse(&["tools", "check", "--rules"]) else {
        panic!("expected check")
    };
    assert_eq!(check.rules, Some(vec![]));
    for args in [
        vec!["tools", "remember", "topic", "--tags"],
        vec!["tools", "who", "question", "--hypotheses"],
        vec!["tools", "reason", "question", "--assumptions"],
    ] {
        let ToolCommand::Knowledge(command) = parse(&args) else {
            panic!("expected knowledge")
        };
        let (name, request) = command.request().unwrap();
        let key = match name {
            "ken_remember" => "tags",
            "ken_who" => "hypotheses",
            _ => "assumptions",
        };
        assert_eq!(request[key], json!([]));
    }
    let f = Fixture::new();
    fs::write(f.root.path().join("code.py"), "TOKEN = 'native_needle'\n").unwrap();
    for (flags, mode) in [
        (vec!["--literal", "--no-literal"], "bm25"),
        (vec!["--no-literal", "--literal"], "literal"),
    ] {
        let args = vec!["find", "native_needle", "--scope", "text"]
            .into_iter()
            .chain(flags)
            .collect::<Vec<_>>();
        assert_eq!(f.tool(&args)["mode"], mode);
    }
    assert_eq!(
        f.tool(&["rule", "--action", "list", "--full", "--no-full"]),
        json!({"rules":[]})
    );
    f.tool(&["rank", "--scope", "project", "--explain", "--no-explain"]);
    let fact = atom("owns", "native", "flags");
    assert_eq!(
        f.tool(&[
            "reason-record",
            "negative-retract",
            "--retract",
            "--no-retract",
            "--facts",
            &fact
        ])["changed"],
        true
    );
    assert_eq!(
        f.tool(&["reason", "What follows?", "--goal", &fact])["status"],
        "supported"
    );
    let who = f.run(&[
        "tools",
        "who",
        "question",
        "--no-verify",
        "--include-tests",
        "--no-include-tests",
        "--full",
        "--no-full",
        "--limit",
        "0",
    ]);
    assert_eq!(who.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&who.stderr).contains("limit must be 1..10"));
}
