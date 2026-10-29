use super::{Fixture, configure_registered, evidence, original, response};
use flate2::read::GzDecoder;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    fs,
    io::{BufRead, BufReader, Read, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    sync::mpsc::{self, Receiver},
    thread,
    time::{Duration, Instant},
};

struct Client {
    child: Child,
    input: Option<ChildStdin>,
    frames: Receiver<Vec<u8>>,
    reader: Option<thread::JoinHandle<()>>,
    retained: Option<PathBuf>,
    stderr: PathBuf,
}
impl Client {
    fn new(fixture: &Fixture) -> Self {
        let stderr = fixture.directory.path().join("mcp.stderr");
        let mut command = Command::new(evidence::native());
        evidence::application_environment(&mut command);
        command
            .arg("--resources")
            .arg(&fixture.installation)
            .arg("mcp")
            .arg(&fixture.project)
            .current_dir(fixture.directory.path())
            .env("HOME", fixture.directory.path().join("home"))
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(fs::File::create(&stderr).unwrap());
        let mut child = command.spawn().unwrap();
        let retained = evidence::start(
            child.id(),
            &command,
            &fixture.installation,
            &fixture.project,
        );
        if let Some(root) = &retained {
            fs::write(root.join("stdin"), b"").unwrap();
        }
        let input = child.stdin.take();
        let output = child.stdout.take().unwrap();
        let (tx, frames) = mpsc::channel();
        let stdout = retained
            .as_ref()
            .map(|root| fs::File::create(root.join("stdout")).unwrap());
        let reader = thread::spawn(move || {
            let mut output = BufReader::new(output);
            let mut stdout = stdout;
            loop {
                let mut line = Vec::new();
                if output.read_until(b'\n', &mut line).unwrap() == 0 {
                    break;
                }
                if let Some(stream) = &mut stdout {
                    stream.write_all(&line).unwrap();
                }
                if tx.send(line).is_err() {
                    break;
                }
            }
        });
        Self {
            child,
            input,
            frames,
            reader: Some(reader),
            retained,
            stderr,
        }
    }
    fn raw(&mut self, frame: &[u8]) {
        if let Some(root) = &self.retained {
            let mut stream = fs::OpenOptions::new()
                .append(true)
                .open(root.join("stdin"))
                .unwrap();
            stream.write_all(frame).unwrap();
            stream.write_all(b"\n").unwrap();
        }
        let input = self.input.as_mut().unwrap();
        input.write_all(frame).unwrap();
        input.write_all(b"\n").unwrap();
        input.flush().unwrap();
    }
    fn send(&mut self, frame: &Value) {
        self.raw(frame.to_string().as_bytes());
    }
    fn receive(&mut self) -> Value {
        let line = self
            .frames
            .recv_timeout(Duration::from_secs(120))
            .expect("one framed MCP response before the process deadline");
        serde_json::from_slice(&line)
            .unwrap_or_else(|e| panic!("nonprotocol stdout: {e}: {line:?}"))
    }
    fn call(&mut self, id: i64, args: Value) -> Value {
        self.send(&json!({"jsonrpc":"2.0","id":id,"method":"tools/call","params":{"name":"ken_find","arguments":args}}));
        self.receive()
    }
    fn begin_initialization(&mut self) {
        self.send(&json!({"jsonrpc":"2.0","id":"init","method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"native-validation","version":"1"}}}));
        let reply = self.receive();
        assert_eq!(reply["id"], "init");
        assert_eq!(reply["result"]["protocolVersion"], "2025-11-25");
        assert!(reply["result"]["capabilities"]["tools"].is_object());
    }
    fn initialize(&mut self) {
        self.begin_initialization();
        self.send(&json!({"jsonrpc":"2.0","method":"notifications/initialized"}));
    }
    fn finish(mut self) {
        self.input.take();
        let deadline = Instant::now() + Duration::from_secs(30);
        loop {
            if let Some(status) = self.child.try_wait().unwrap() {
                if let Some(root) = &self.retained {
                    fs::copy(&self.stderr, root.join("stderr")).unwrap();
                    fs::write(root.join("exit"), status.code().unwrap().to_string()).unwrap();
                }
                assert!(status.success(), "MCP did not exit successfully: {status}");
                break;
            }
            assert!(Instant::now() < deadline, "MCP did not close after EOF");
            thread::sleep(Duration::from_millis(5));
        }
        self.reader.take().unwrap().join().unwrap();
        assert!(
            self.frames.try_recv().is_err(),
            "unsolicited or unframed stdout at EOF"
        );
    }
}
impl Drop for Client {
    fn drop(&mut self) {
        if self.child.try_wait().ok().flatten().is_none() {
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
        if let Some(reader) = self.reader.take() {
            let _ = reader.join();
        }
        if let Some(root) = &self.retained {
            let _ = fs::copy(&self.stderr, root.join("stderr"));
        }
    }
}
fn text(reply: &Value) -> &str {
    assert_eq!(reply["result"]["isError"], false, "{reply}");
    reply["result"]["content"][0]["text"].as_str().unwrap()
}

#[test]
fn original_stdio_default_json_and_newline_results_match_independent_capture() {
    let bytes = include_bytes!("../fixtures/mcp-default-reference.json.gz");
    assert_eq!(bytes.len(), 11014);
    assert_eq!(
        format!("{:x}", Sha256::digest(bytes)),
        "8219d4c0881b77e5443a2c89c2f3728b75edce566e190bc4f0de6b39e484dc01"
    );
    let mut raw = String::new();
    GzDecoder::new(&bytes[..]).read_to_string(&mut raw).unwrap();
    let original: Value = serde_json::from_str(&raw).unwrap();
    assert_eq!(original["rows"].as_array().unwrap().len(), 7);
    assert_eq!(original["unfinished"]["completed"], false);
    let fixture = Fixture::new();
    let mut client = Client::new(&fixture);
    client.initialize();
    for row in &original["rows"].as_array().unwrap()[2..] {
        client.send(&row["request"]);
        let actual = client.receive();
        assert_eq!(actual["id"], row["response"]["id"]);
        let got = text(&actual);
        let want = text(&row["response"]);
        if want.starts_with('{') {
            assert_eq!(
                serde_json::from_str::<Value>(got).unwrap(),
                serde_json::from_str::<Value>(want).unwrap()
            );
        } else {
            assert_eq!(got, want);
        }
    }
    // The original SDK failed to answer this escaped Python text. Native framing
    // preserves it through the shared domain instead of stalling the channel.
    client.raw(br#"{"jsonrpc":"2.0","id":99,"method":"tools/call","params":{"name":"ken_find","arguments":{"query":"value\ud800name","scope":"symbols"}}}"#);
    assert_eq!(text(&client.receive()), "No matches.");
    client.finish();
    assert!(!fixture.directory.path().join("cache").exists());
}

#[test]
fn malformed_frames_invalid_calls_and_notifications_do_not_poison_the_stdio_session() {
    let fixture = Fixture::new();
    let mut client = Client::new(&fixture);
    client.send(&json!({"jsonrpc":"2.0","id":1,"method":"tools/list"}));
    assert_eq!(client.receive()["error"]["code"], -32002);
    client.raw(b"{");
    assert_eq!(client.receive()["error"]["code"], -32700);
    client.raw(b"[]");
    assert_eq!(client.receive()["error"]["code"], -32600);
    client.initialize();
    client.send(&json!({"jsonrpc":"2.0","id":2,"method":"tools/list"}));
    let listed = client.receive();
    let tools = listed["result"]["tools"].as_array().unwrap();
    assert_eq!(
        tools
            .iter()
            .map(|tool| tool["name"].as_str().unwrap())
            .collect::<Vec<_>>(),
        vec!["ken_find", "ken_read", "ken_related", "ken_rank"]
    );
    assert_eq!(tools[0]["name"], "ken_find");
    assert_eq!(
        tools[0]["inputSchema"]["properties"]["scope"]["enum"],
        json!(["files", "symbols", "text", "tests"])
    );
    let invalid = client.call(3, json!({"query":"find value","scope":"wiring"}));
    assert_eq!(invalid["result"]["isError"], true);
    client.send(&json!({"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"missing","arguments":{}}}));
    assert_eq!(client.receive()["error"]["code"], -32602);
    client.send(&json!({"jsonrpc":"2.0","id":5,"method":"unknown"}));
    assert_eq!(client.receive()["error"]["code"], -32601);
    client.send(&json!({"jsonrpc":"2.0","method":"notifications/unknown"}));
    client.send(&json!({"jsonrpc":"2.0","id":6,"method":"ping"}));
    let pong = client.receive();
    assert_eq!(pong["id"], 6);
    assert_eq!(pong["result"], json!({}));
    client.raw(&vec![b' '; 8 * 1024 * 1024 + 1]);
    assert_eq!(client.receive()["error"]["code"], -32700);
    client.raw(b"\xff");
    assert_eq!(client.receive()["error"]["code"], -32700);
    assert_eq!(
        text(&client.call(7, json!({"query":"find value"}))),
        "No matches."
    );
    client.finish();
}

#[test]
fn invalid_initialized_notification_cannot_enable_tool_execution() {
    let fixture = Fixture::new();
    let mut client = Client::new(&fixture);
    client.begin_initialization();
    client.send(&json!({"jsonrpc":"2.0","method":"notifications/initialized","params":[]}));
    client.send(&json!({"jsonrpc":"2.0","id":1,"method":"tools/list"}));
    assert_eq!(client.receive()["error"]["code"], -32002);
    client.send(&json!({"jsonrpc":"2.0","method":"notifications/initialized"}));
    assert_eq!(
        text(&client.call(2, json!({"query":"find value"}))),
        "No matches."
    );
    client.finish();
}

#[test]
fn call_envelope_requires_an_argument_object_before_tool_validation() {
    let fixture = Fixture::new();
    let mut client = Client::new(&fixture);
    client.initialize();
    for (id, args) in [(1, json!([])), (2, json!(false)), (3, json!("query"))] {
        client.send(&json!({"jsonrpc":"2.0","id":id,"method":"tools/call","params":{"name":"ken_find","arguments":args}}));
        assert_eq!(client.receive()["error"]["code"], -32602);
    }
    assert_eq!(
        text(&client.call(4, json!({"query":"find value"}))),
        "No matches."
    );
    client.finish();
}

#[test]
fn initialization_negotiates_versions_without_extra_client_metadata_constraints() {
    for version in ["2025-11-25", "2099-01-01"] {
        let fixture = Fixture::new();
        let mut client = Client::new(&fixture);
        client.send(&json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":version,"capabilities":{},"clientInfo":{"name":"","version":""}}}));
        assert_eq!(client.receive()["result"]["protocolVersion"], "2025-11-25");
        client.send(&json!({"jsonrpc":"2.0","method":"notifications/initialized"}));
        assert_eq!(
            text(&client.call(2, json!({"query":"find value"}))),
            "No matches."
        );
        client.finish();
    }
}

#[test]
fn missing_installation_retries_and_exact_source_remains_cold_in_the_same_process() {
    let fixture = Fixture::new();
    let held = fixture.installation.with_extension("held");
    fs::rename(&fixture.installation, &held).unwrap();
    let mut client = Client::new(&fixture);
    client.initialize();
    let first = client.call(1, json!({"query":"find value","output_format":"json"}));
    let failed: Value = serde_json::from_str(text(&first)).unwrap();
    assert_eq!(failed["ok"], false);
    assert_eq!(failed["code"], "search_preparation_required");
    fs::rename(&held, &fixture.installation).unwrap();
    assert_eq!(
        text(&client.call(2, json!({"query":"find value"}))),
        "No matches."
    );
    fixture
        .index(&json!({"source.py":"def public_transport_unique(value):\n    return value + 3\n"}));
    assert_eq!(
        text(&client.call(
            3,
            json!({"query":"public_transport_unique","scope":"symbols"})
        )),
        "source.py:1-2 :: public_transport_unique\n1 | def public_transport_unique(value):\n2 |     return value + 3"
    );
    client.finish();
    assert!(!fixture.directory.path().join("cache").exists());
    assert!(!fixture.directory.path().join("owned").exists());
}

#[test]
fn unicode_json_spellings_share_the_exact_cold_mcp_route() {
    let fixture = Fixture::new();
    fixture.index(&json!({"source.py":"def 𐐀(value):\n    return value + 3\n"}));
    let mut client = Client::new(&fixture);
    client.initialize();
    let literal = client.call(1, json!({"scope":"symbols","query":"source.py::𐐀"}));
    assert!(text(&literal).contains("def 𐐀(value)"));
    client.raw(br#"{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"ken_find","arguments":{"scope":"symbols","query":"source.py::\ud801\udc00"}}}"#);
    let escaped = client.receive();
    assert_eq!(text(&escaped), text(&literal));
    client.raw(br#"{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"ken_find","arguments":{"scope":"symbols","query":"source.py::\ud801\udc00","output_format":"json"}}}"#);
    let reply = client.receive();
    let result: Value = serde_json::from_str(text(&reply)).unwrap();
    assert_eq!(result["query"], "source.py::𐐀");
    assert_eq!(result["profile_version"], "best-exact-source-v1");
    assert_eq!(result["results"][0]["entity"]["qualname"], "𐐀");
    client.finish();
    assert!(!fixture.directory.path().join("cache").exists());
    assert!(!fixture.directory.path().join("owned").exists());
}

fn link_tree(source: &Path, target: &Path) {
    fs::create_dir_all(target).unwrap();
    for entry in fs::read_dir(source).unwrap() {
        let entry = entry.unwrap();
        let path = entry.path();
        let next = target.join(entry.file_name());
        if path.is_dir() {
            link_tree(&path, &next)
        } else {
            fs::hard_link(fs::canonicalize(path).unwrap(), next).unwrap();
        }
    }
}
#[test]
fn real_stdio_registered_models_survive_source_withdrawal_and_database_replacement() {
    let fixture = Fixture::new();
    let original = original();
    fixture.index(&original["input"]["projects"][0]["files"]);
    configure_registered(&fixture);
    let mut config: Value =
        serde_json::from_slice(&fs::read(&fixture.installation).unwrap()).unwrap();
    for (i, source) in config["sources"]
        .as_object_mut()
        .unwrap()
        .values_mut()
        .enumerate()
    {
        let path = Path::new(source.as_str().unwrap());
        let alias = fixture
            .directory
            .path()
            .join("aliases")
            .join(i.to_string())
            .join(path.file_name().unwrap());
        link_tree(path, &alias);
        *source = json!(alias);
    }
    fs::write(&fixture.installation, config.to_string()).unwrap();
    let mut client = Client::new(&fixture);
    client.initialize();
    let args = json!({"query":"Preserve the exception cause","scope":"symbols","piece_kind":"symbol","full":true,"output_format":"json"});
    let first = client.call(1, args.clone());
    let actual: Value = serde_json::from_str(text(&first)).unwrap();
    response::real_response(&actual, &original["events"][0]["result"], "stdio original");
    fs::rename(
        fixture.directory.path().join("aliases"),
        fixture.directory.path().join("withheld-aliases"),
    )
    .unwrap();
    let second = client.call(2, args.clone());
    let repeated: Value = serde_json::from_str(text(&second)).unwrap();
    response::real_response(&repeated, &actual, "owned repeated stdio");
    let database = fixture.project.join(".ken/ken.db");
    let generation = |path: &Path| {
        let db = ken_store::ProjectDatabase::open(path).unwrap();
        ken_retrieval::storage::generation(db.connection()).unwrap()
    };
    let old_generation = generation(&database);
    fs::rename(&database, fixture.project.join(".ken/previous.db")).unwrap();
    {
        let mut db = ken_store::ProjectDatabase::open(&database).unwrap();
        db.initialize().unwrap();
    }
    let mut files = original["input"]["projects"][0]["files"].clone();
    let source = files["pkg/reader.py"]
        .as_str()
        .unwrap()
        .replace("def annotate(", "def decorate(");
    files["pkg/reader.py"] = json!(source);
    fixture.index(&files);
    let fresh = client.call(3, args);
    let current: Value = serde_json::from_str(text(&fresh)).unwrap();
    assert_eq!(
        generation(&database),
        old_generation,
        "the replacement must collide with the old generation to exercise database identity"
    );
    assert_eq!(current["results"][0]["entity"]["qualname"], "decorate");
    assert!(
        current["results"][0]["evidence"][0]["content"]
            .as_str()
            .unwrap()
            .contains("def decorate(")
    );
    assert_eq!(current["results"][0]["stale"], false);
    client.finish();
}
