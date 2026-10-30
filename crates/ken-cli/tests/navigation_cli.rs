#[path = "support/public_evidence.rs"]
#[allow(dead_code)]
mod evidence;
#[path = "../../ken-search/tests/support/live_codeflow.rs"]
mod live_codeflow;
#[path = "../../ken-search/tests/support/project_orientation.rs"]
mod project_orientation;
#[path = "../../ken-search/tests/support/responsibility_profile.rs"]
mod responsibility_profile;
#[path = "../../ken-search/tests/support/navigation.rs"]
#[allow(dead_code)]
mod support;
#[path = "../../ken-search/tests/support/worktree_text.rs"]
mod worktree_text;
use serde_json::{Value, json};
use std::{
    fs,
    io::{BufRead, BufReader, Write},
    process::{Child, ChildStdin, Command, Stdio},
    sync::mpsc::{self, Receiver},
    thread,
    time::{Duration, Instant},
};
use support::*;

fn command(fixture: &Fixture) -> Command {
    let mut command = Command::new(evidence::native());
    command
        .arg("--resources")
        .arg(fixture.paths.root().join("missing-installation.json"))
        .current_dir(fixture.paths.root())
        .env_clear()
        .env("HOME", fixture.paths.root().join("home"))
        .env("PATH", "")
        .env("LANG", "C.UTF-8");
    command
}
#[test]
fn actual_cli_tools_match_original_json_and_compact_without_model_installation() {
    let fixture = Fixture::new();
    let hash = fixture.database_hash();
    for row in reference()["public"].as_array().unwrap() {
        for json_output in [false, true] {
            let mut args = cli_args(row, json_output);
            args.splice(
                1..1,
                [
                    "--path".into(),
                    fixture.paths.root().to_string_lossy().into_owned(),
                ],
            );
            let got = command(&fixture).args(args).output().unwrap();
            assert!(
                got.status.success(),
                "{}: {}",
                row["request"],
                String::from_utf8_lossy(&got.stderr)
            );
            assert!(got.stderr.is_empty());
            if json_output {
                assert_eq!(
                    serde_json::from_slice::<Value>(&got.stdout).unwrap(),
                    row["result"],
                    "{}",
                    row["request"]
                );
            } else {
                assert_eq!(
                    String::from_utf8(got.stdout).unwrap(),
                    row["compact"].as_str().unwrap().to_owned() + "\n",
                    "{}",
                    row["request"]
                );
            }
        }
    }
    let listed = command(&fixture)
        .args(["tools", "--list"])
        .output()
        .unwrap();
    assert!(listed.status.success());
    let text = String::from_utf8(listed.stdout).unwrap();
    assert!(text.contains("ken_read") && text.contains("ken_related"));
    let profile = command(&fixture)
        .args(["tools", "read", "src/service.py", "--include", "profile"])
        .output()
        .unwrap();
    assert!(profile.status.success());
    assert!(
        String::from_utf8(profile.stdout)
            .unwrap()
            .contains("evidence_strength")
    );
    assert_eq!(fixture.database_hash(), hash);
    assert!(!fixture.paths.root().join("cache").exists());
    assert!(!fixture.paths.root().join("owned").exists());
}

struct Mcp {
    child: Child,
    input: Option<ChildStdin>,
    frames: Receiver<String>,
    reader: Option<thread::JoinHandle<()>>,
}
impl Mcp {
    fn new(fixture: &Fixture) -> Self {
        Self::from_command(command(fixture).arg("mcp").arg(fixture.paths.root()))
    }
    fn from_command(command: &mut Command) -> Self {
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        let input = child.stdin.take();
        let output = child.stdout.take().unwrap();
        let (tx, frames) = mpsc::channel();
        let reader = thread::spawn(move || {
            for line in BufReader::new(output).lines() {
                if tx.send(line.unwrap()).is_err() {
                    break;
                }
            }
        });
        Self {
            child,
            input,
            frames,
            reader: Some(reader),
        }
    }
    fn send(&mut self, value: &Value) {
        writeln!(self.input.as_mut().unwrap(), "{value}").unwrap();
        self.input.as_mut().unwrap().flush().unwrap();
    }
    fn receive(&self) -> Value {
        serde_json::from_str(
            &self
                .frames
                .recv_timeout(Duration::from_secs(30))
                .expect("native navigation MCP response deadline"),
        )
        .unwrap()
    }
    fn initialize(&mut self) {
        self.send(&json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"navigation-test","version":"1"}}}));
        assert_eq!(self.receive()["result"]["protocolVersion"], "2025-11-25");
        self.send(&json!({"jsonrpc":"2.0","method":"notifications/initialized"}));
    }
    fn call(&mut self, id: i64, tool: &str, args: Value) -> Value {
        self.send(&json!({"jsonrpc":"2.0","id":id,"method":"tools/call","params":{"name":tool,"arguments":args}}));
        self.receive()
    }
    fn finish(mut self) {
        self.input.take();
        let deadline = Instant::now() + Duration::from_secs(30);
        loop {
            if let Some(status) = self.child.try_wait().unwrap() {
                assert!(status.success());
                break;
            }
            assert!(Instant::now() < deadline);
            thread::sleep(Duration::from_millis(5));
        }
        self.reader.take().unwrap().join().unwrap();
        assert!(self.frames.try_recv().is_err());
    }
}
impl Drop for Mcp {
    fn drop(&mut self) {
        if self.child.try_wait().ok().flatten().is_none() {
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
        if let Some(reader) = self.reader.take() {
            let _ = reader.join();
        }
    }
}
fn text(reply: &Value) -> &str {
    assert_eq!(reply["result"]["isError"], false, "{reply}");
    reply["result"]["content"][0]["text"].as_str().unwrap()
}
#[test]
fn actual_stdio_navigation_matches_original_and_observes_replaced_database() {
    let fixture = Fixture::new();
    let hash = fixture.database_hash();
    let mut client = Mcp::new(&fixture);
    client.initialize();
    client.send(&json!({"jsonrpc":"2.0","id":2,"method":"tools/list"}));
    let listed = client.receive();
    let names = listed["result"]["tools"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v["name"].as_str().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(
        names
            .iter()
            .copied()
            .filter(|name| ["ken_find", "ken_read", "ken_related", "ken_rank"].contains(name))
            .collect::<Vec<_>>(),
        vec!["ken_find", "ken_read", "ken_related", "ken_rank"]
    );
    let mut id = 3;
    for row in reference()["public"].as_array().unwrap() {
        for json_output in [false, true] {
            let mut args = row["request"]["args"].clone();
            if json_output {
                args["output_format"] = json!("json");
            }
            let reply = client.call(id, row["request"]["tool"].as_str().unwrap(), args);
            id += 1;
            if json_output {
                assert_eq!(
                    serde_json::from_str::<Value>(text(&reply)).unwrap(),
                    row["result"],
                    "{}",
                    row["request"]
                );
            } else {
                assert_eq!(
                    text(&reply),
                    row["compact"].as_str().unwrap(),
                    "{}",
                    row["request"]
                );
            }
        }
    }
    let failure = client.call(
        id,
        "ken_related",
        json!({"target":"src/service.py","relation":"cochange"}),
    );
    assert_eq!(failure["result"]["isError"], true);
    id += 1;
    let confined = client.call(
        id,
        "ken_read",
        json!({"path":"../outside.py","include":["source"]}),
    );
    assert_eq!(confined["result"]["isError"], true);
    id += 1;
    assert_eq!(fixture.database_hash(), hash);
    let replacement = Fixture::new();
    let conn = rusqlite::Connection::open(replacement.paths.db()).unwrap();
    conn.execute(
        "UPDATE ci_symbols SET docstring='new navigation database' WHERE qualname='Service'",
        [],
    )
    .unwrap();
    drop(conn);
    fs::rename(replacement.paths.db(), fixture.paths.db()).unwrap();
    let result=client.call(id,"ken_read",json!({"path":"src/service.py","qualname":"Service","include":["symbols","docstrings"],"output_format":"json"}));
    let value: Value = serde_json::from_str(text(&result)).unwrap();
    assert_eq!(
        value["symbol"]["symbol"]["docstring"],
        "new navigation database"
    );
    client.finish();
    assert!(!fixture.paths.root().join("cache").exists());
    assert!(!fixture.paths.root().join("owned").exists());
}

#[test]
fn actual_text_cli_and_stdio_match_original_history_without_models() {
    let reference = worktree_text::reference();
    for json_output in [false, true] {
        let fixture = worktree_text::fixture();
        let mut rows = reference["rows"].as_array().unwrap().iter();
        for event in reference["events"].as_array().unwrap() {
            if event["action"] != "query" {
                worktree_text::apply(&fixture, event);
                continue;
            }
            let row = rows.next().unwrap();
            let args = worktree_text::cli_args(&row["args"], json_output);
            let got = command(&fixture).args(args).output().unwrap();
            assert!(
                got.status.success(),
                "{}: {}",
                row["args"],
                String::from_utf8_lossy(&got.stderr)
            );
            assert!(got.stderr.is_empty());
            if json_output {
                assert_eq!(
                    serde_json::from_slice::<Value>(&got.stdout).unwrap(),
                    row["result"],
                    "{}",
                    row["args"]
                );
            } else {
                assert_eq!(
                    String::from_utf8(got.stdout).unwrap(),
                    row["compact"].as_str().unwrap().to_owned() + "\n",
                    "{}",
                    row["args"]
                );
            }
        }
        let fixture = worktree_text::fixture();
        let mut client = Mcp::new(&fixture);
        client.initialize();
        let mut rows = reference["rows"].as_array().unwrap().iter();
        for (id, event) in reference["events"].as_array().unwrap().iter().enumerate() {
            if event["action"] != "query" {
                worktree_text::apply(&fixture, event);
                continue;
            }
            let row = rows.next().unwrap();
            let mut args = row["args"].clone();
            if json_output {
                args["output_format"] = json!("json");
            }
            let reply = client.call(id as i64 + 2, "ken_find", args);
            if json_output {
                assert_eq!(
                    serde_json::from_str::<Value>(text(&reply)).unwrap(),
                    row["result"],
                    "{}",
                    row["args"]
                );
            } else {
                assert_eq!(
                    text(&reply),
                    row["compact"].as_str().unwrap(),
                    "{}",
                    row["args"]
                );
            }
        }
        fs::write(
            fixture.paths.root().join("src/service.py"),
            "INVALID_FORMAT_SENTINEL",
        )
        .unwrap();
        let hash = fixture.database_hash();
        for (id, response) in [(98, "auto"), (99, "legacy")] {
            let rejected = client.call(id, "ken_find", json!({"query":"INVALID_FORMAT_SENTINEL","scope":"text","response_format":response,"output_format":"invalid"}));
            assert_eq!(rejected["result"]["isError"], true);
            assert_eq!(fixture.database_hash(), hash);
        }
        let reply = client.call(
            100,
            "ken_find",
            json!({"query":"Service","scope":"text","response_format":"legacy"}),
        );
        assert_eq!(
            serde_json::from_str::<Value>(text(&reply)).unwrap()["mode"],
            "bm25"
        );
        let denied = client.call(
            101,
            "ken_find",
            json!({"query":"Service","scope":"text","response_format":"compact"}),
        );
        assert_eq!(denied["result"]["isError"], true);
        client.finish();
        assert!(!fixture.paths.root().join("cache").exists());
    }
}

#[test]
fn actual_profile_cli_and_stdio_match_original_without_models() {
    let fixture = responsibility_profile::fixture();
    let hash = fixture.database_hash();
    let mut client = Mcp::new(&fixture);
    client.initialize();
    for (id, row) in responsibility_profile::reference()["public"]
        .as_array()
        .unwrap()
        .iter()
        .enumerate()
    {
        for json_output in [false, true] {
            let mut args = row["args"].clone();
            if json_output {
                args["output_format"] = json!("json");
            }
            let reply = client.call(
                id as i64 * 2 + if json_output { 3 } else { 2 },
                "ken_read",
                args,
            );
            let cli_row = json!({"request":{"tool":"ken_read","args":row["args"]}});
            let got = command(&fixture)
                .args(cli_args(&cli_row, json_output))
                .output()
                .unwrap();
            assert!(
                got.status.success(),
                "{}",
                String::from_utf8_lossy(&got.stderr)
            );
            assert!(got.stderr.is_empty());
            if json_output {
                assert_eq!(
                    serde_json::from_str::<Value>(text(&reply)).unwrap(),
                    row["result"]
                );
                assert_eq!(
                    serde_json::from_slice::<Value>(&got.stdout).unwrap(),
                    row["result"]
                );
            } else {
                assert_eq!(text(&reply), row["compact"].as_str().unwrap());
                assert_eq!(
                    String::from_utf8(got.stdout).unwrap(),
                    row["compact"].as_str().unwrap().to_owned() + "\n"
                );
            }
        }
    }
    client.finish();
    assert_eq!(fixture.database_hash(), hash);
}

#[test]
fn actual_rank_cli_and_stdio_match_original_project_architecture_and_changes() {
    fn run(fixture: &Fixture, rows: &[Value], git: bool) {
        let hash = fixture.database_hash();
        let make_command = || {
            let mut cmd = command(fixture);
            if git {
                cmd.env("PATH", std::env::var_os("PATH").unwrap());
            }
            cmd
        };
        let mut client = if git {
            Mcp::from_command(make_command().arg("mcp").arg(fixture.paths.root()))
        } else {
            Mcp::new(fixture)
        };
        client.initialize();
        for (id, row) in rows.iter().enumerate() {
            for json_output in [false, true] {
                let mut args = row["args"].clone();
                if json_output {
                    args["output_format"] = json!("json");
                }
                let reply = client.call(
                    id as i64 * 2 + if json_output { 3 } else { 2 },
                    "ken_rank",
                    args,
                );
                let got = make_command()
                    .args(project_orientation::cli_args(&row["args"], json_output))
                    .output()
                    .unwrap();
                assert!(
                    got.status.success(),
                    "{}",
                    String::from_utf8_lossy(&got.stderr)
                );
                assert!(got.stderr.is_empty());
                if json_output {
                    assert_eq!(
                        serde_json::from_str::<Value>(text(&reply)).unwrap(),
                        row["result"],
                        "{}",
                        row["args"]
                    );
                    assert_eq!(
                        serde_json::from_slice::<Value>(&got.stdout).unwrap(),
                        row["result"],
                        "{}",
                        row["args"]
                    );
                } else {
                    assert_eq!(
                        text(&reply),
                        row["compact"].as_str().unwrap(),
                        "{}",
                        row["args"]
                    );
                    assert_eq!(
                        String::from_utf8(got.stdout).unwrap(),
                        row["compact"].as_str().unwrap().to_owned() + "\n",
                        "{}",
                        row["args"]
                    );
                }
            }
        }
        let failure = client.call(100, "ken_rank", json!({"scope":"session"}));
        assert_eq!(failure["result"]["isError"], true);
        client.finish();
        assert_eq!(fixture.database_hash(), hash);
    }
    let reference = project_orientation::reference();
    for (input, case) in reference["input"]
        .as_array()
        .unwrap()
        .iter()
        .zip(reference["cases"].as_array().unwrap())
    {
        run(
            &project_orientation::graph_fixture(input),
            case["public"].as_array().unwrap(),
            false,
        );
    }
    run(
        &project_orientation::changes_fixture(),
        reference["changes"].as_array().unwrap(),
        true,
    );
}

#[test]
fn actual_live_codeflow_cli_and_stdio_match_original_with_grammar_only_resources() {
    let fixture = live_codeflow::fixture();
    let hash = fixture.database_hash();
    let mut client = Mcp::new(&fixture);
    client.initialize();
    let failed = client.call(
        2,
        "ken_related",
        json!({"target":"run","relation":"callees"}),
    );
    assert_eq!(failed["result"]["isError"], true);
    live_codeflow::installation(&fixture);
    for (i, row) in live_codeflow::reference()["public"]
        .as_array()
        .unwrap()
        .iter()
        .enumerate()
    {
        for json_output in [false, true] {
            let mut args = row["request"]["args"].clone();
            if json_output {
                args["output_format"] = json!("json");
            }
            let reply = client.call(
                i as i64 * 2 + if json_output { 4 } else { 3 },
                row["request"]["tool"].as_str().unwrap(),
                args,
            );
            let got = command(&fixture)
                .args(live_codeflow::cli_args(row, json_output))
                .output()
                .unwrap();
            assert!(
                got.status.success(),
                "{}",
                String::from_utf8_lossy(&got.stderr)
            );
            assert!(got.stderr.is_empty());
            if json_output {
                assert_eq!(
                    serde_json::from_str::<Value>(text(&reply)).unwrap(),
                    row["result"],
                    "{}",
                    row["request"]
                );
                assert_eq!(
                    serde_json::from_slice::<Value>(&got.stdout).unwrap(),
                    row["result"],
                    "{}",
                    row["request"]
                );
            } else {
                assert_eq!(
                    text(&reply),
                    row["compact"].as_str().unwrap(),
                    "{}",
                    row["request"]
                );
                assert_eq!(
                    String::from_utf8(got.stdout).unwrap(),
                    row["compact"].as_str().unwrap().to_owned() + "\n",
                    "{}",
                    row["request"]
                );
            }
        }
    }
    let api = fixture.paths.root().join("api.py");
    let source = fs::read_to_string(&api)
        .unwrap()
        .replace("process()", "helper()");
    fs::write(api, source).unwrap();
    let reply = client.call(
        100,
        "ken_related",
        json!({"target":"run","relation":"callees","output_format":"json"}),
    );
    let changed: Value = serde_json::from_str(text(&reply)).unwrap();
    assert_eq!(changed["callees"].as_array().unwrap().len(), 2);
    assert!(
        changed["callees"]
            .as_array()
            .unwrap()
            .iter()
            .all(|edge| edge["to_qualname"] == "helper")
    );
    let legacy = client.call(
        101,
        "ken_find",
        json!({"query":"env","scope":"wiring","response_format":"legacy"}),
    );
    assert!(serde_json::from_str::<Value>(text(&legacy)).unwrap()["wiring"].is_array());
    client.finish();
    assert_eq!(fixture.database_hash(), hash);
    assert!(!fixture.paths.root().join("cache").exists());
}
