#[path = "../../ken-search/tests/support/navigation.rs"]
#[allow(dead_code)]
mod support;
use serde_json::{Value, json};
use std::{
    io::{Read, Write},
    net::TcpListener,
    process::{Command, Stdio},
    thread,
};
use support::Fixture;
fn command(fixture: &Fixture) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_ken-rs"));
    command
        .arg("--resources")
        .arg(fixture.paths.root().join("absent.json"))
        .env_clear()
        .env("HOME", fixture.paths.root())
        .env("PATH", "")
        .current_dir(fixture.paths.root());
    command
}
fn http(
    fixture: &Fixture,
    expected_path: &'static str,
    response: Value,
) -> thread::JoinHandle<Value> {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    std::fs::write(
        fixture.paths.port(),
        listener.local_addr().unwrap().port().to_string(),
    )
    .unwrap();
    thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(std::time::Duration::from_secs(10)))
            .unwrap();
        let mut bytes = Vec::new();
        let split = loop {
            let mut chunk = [0; 4096];
            let n = stream.read(&mut chunk).unwrap();
            assert_ne!(n, 0);
            bytes.extend_from_slice(&chunk[..n]);
            if let Some(split) = bytes.windows(4).position(|b| b == b"\r\n\r\n") {
                break split;
            }
        };
        let head = String::from_utf8(bytes[..split].to_vec()).unwrap();
        assert!(
            head.starts_with(&format!("POST {expected_path} HTTP/1.1\r\n")),
            "{head}"
        );
        assert!(head.contains("Authorization: Bearer "), "{head}");
        let len: usize = head
            .lines()
            .find_map(|l| l.strip_prefix("Content-Length: "))
            .unwrap()
            .parse()
            .unwrap();
        while bytes.len() - split - 4 < len {
            let mut chunk = [0; 4096];
            let n = stream.read(&mut chunk).unwrap();
            assert_ne!(n, 0);
            bytes.extend_from_slice(&chunk[..n]);
        }
        let body = serde_json::from_slice(&bytes[split + 4..split + 4 + len]).unwrap();
        let response = response.to_string();
        write!(stream,"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{response}",response.len()).unwrap();
        body
    })
}
#[test]
fn native_session_rank_and_ordinary_rank_share_the_authenticated_daemon_without_models() {
    let fixture = Fixture::new();
    std::fs::write(
        fixture.paths.meta(),
        json!({"project_id":"native-cli","auth_token":"native-token"}).to_string(),
    )
    .unwrap();
    let server = http(
        &fixture,
        "/rank",
        json!({"ok":true,"context_block":"<context-rank>π</context-rank>","files":2}),
    );
    let output = command(&fixture)
        .args([
            "tools",
            "--json",
            "rank",
            "--scope",
            "session",
            "context π",
            "--verbose",
            "2",
            "--max-chars",
            "900",
        ])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(
        serde_json::from_slice::<Value>(&output.stdout).unwrap()["files"],
        2
    );
    let sent = server.join().unwrap();
    assert_eq!(sent["query"], "context π");
    assert_eq!(sent["verbose"], 2);
    assert_eq!(sent["max_chars"], 900);
    let server = http(
        &fixture,
        "/explain",
        json!({"ok":true,"channels":{"explicit":[]}}),
    );
    let output = command(&fixture)
        .args(["explain", "context π", "--json"])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(serde_json::from_slice::<Value>(&output.stdout).unwrap()["channels"].is_object());
    assert_eq!(server.join().unwrap()["query"], "context π");
}
#[test]
fn native_hook_normalizes_host_payload_and_only_prints_injected_context() {
    let fixture = Fixture::new();
    std::fs::write(
        fixture.paths.meta(),
        json!({"project_id":"native-cli","auth_token":"native-token"}).to_string(),
    )
    .unwrap();
    let server = http(
        &fixture,
        "/prompts",
        json!({"ok":true,"context_block":"<context-rank>λ</context-rank>","private":"do not print"}),
    );
    let mut child = command(&fixture)
        .args(["hook", "user-prompt"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(br#"{"session_id":"session-native","prompt":"work"}"#)
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(output.status.success());
    assert_eq!(
        String::from_utf8(output.stdout).unwrap(),
        "<context-rank>λ</context-rank>"
    );
    assert_eq!(
        server.join().unwrap(),
        json!({"session_id":"session-native","prompt":"work"})
    );
    let mut child = command(&fixture)
        .args(["hook", "tool-call", "--phase", "post"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(b"invalid JSON")
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(output.status.success());
    assert!(output.stdout.is_empty());
    assert!(!output.stderr.is_empty());
}
#[test]
fn no_history_intent_does_not_prepare_models_and_tool_registry_is_complete() {
    let fixture = Fixture::new();
    let output = command(&fixture)
        .args(["tools", "--json", "find", "context", "--scope", "intent"])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let value: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["files"], json!([]));
    assert!(value["note"].as_str().unwrap().contains("history"));
    let output = command(&fixture)
        .args(["tools", "--list"])
        .output()
        .unwrap();
    assert!(output.status.success());
    let text = String::from_utf8(output.stdout).unwrap();
    for name in [
        "ken_find",
        "ken_query",
        "ken_rule",
        "ken_check",
        "ken_who",
        "ken_read",
        "ken_related",
        "ken_rank",
        "ken_reason_record",
        "ken_reason",
        "ken_calculate",
        "ken_recall",
        "ken_remember",
    ] {
        assert!(
            text.lines()
                .any(|line| line.starts_with(&format!("{name}  "))),
            "missing {name}: {text}"
        );
    }
}
