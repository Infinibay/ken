use ken_core::{
    health::DaemonHealthClient,
    project::{DiscoveryContext, ProjectPaths},
    status::{HealthProbe, StatusReport, read_status},
};
use serde_json::{Map, Value, json};
use std::{
    fs,
    io::{Read, Write},
    net::TcpListener,
    process::Command,
    sync::mpsc,
    thread,
    time::{Duration, Instant},
};
use tempfile::TempDir;

fn project(port: Option<u16>) -> (TempDir, ProjectPaths, DiscoveryContext) {
    let t = TempDir::new().unwrap();
    fs::create_dir(t.path().join(".ken")).unwrap();
    fs::write(
        t.path().join(".ken/meta.json"),
        r#"{"project_id":"fixture","auth_token":"fixture-token"}"#,
    )
    .unwrap();
    if let Some(port) = port {
        fs::write(t.path().join(".ken/daemon.port"), port.to_string()).unwrap();
    }
    let ctx = DiscoveryContext {
        cwd: t.path().into(),
        home: None,
        forced_root: None,
    };
    let paths = ProjectPaths::at(t.path(), &ctx).unwrap();
    (t, paths, ctx)
}
fn metadata() -> Map<String, Value> {
    json!({"auth_token":"fixture-token"})
        .as_object()
        .unwrap()
        .clone()
}
fn server(
    code: u16,
    extra: &str,
    body: &str,
    slow: bool,
) -> (u16, mpsc::Sender<()>, thread::JoinHandle<String>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let (send, receive) = mpsc::channel();
    let extra = extra.to_owned();
    let body = body.to_owned();
    let worker = thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(3)))
            .unwrap();
        let mut request = Vec::new();
        let mut byte = [0];
        while !request.ends_with(b"\r\n\r\n") {
            stream.read_exact(&mut byte).unwrap();
            request.push(byte[0]);
        }
        write!(
            stream,
            "HTTP/1.1 {code} Fixture\r\nContent-Length: {}\r\nConnection: close\r\n{extra}\r\n",
            body.len()
        )
        .unwrap();
        if slow {
            stream.write_all(&body.as_bytes()[..1]).unwrap();
            stream.flush().unwrap();
            let _ = receive.recv_timeout(Duration::from_secs(4));
        } else {
            stream.write_all(body.as_bytes()).unwrap();
        }
        String::from_utf8(request).unwrap()
    });
    (port, send, worker)
}
#[test]
fn sends_bearer_only_to_loopback() {
    let (port, _, worker) = server(
        200,
        "",
        r#"{"sessions_active":2,"running":false,"extra":"kept"}"#,
        false,
    );
    let (t, paths, ctx) = project(Some(port));
    let db = rusqlite::Connection::open(paths.db()).unwrap();
    db.execute_batch(include_str!("../../../src/ken/schema.sql"))
        .unwrap();
    drop(db);
    let StatusReport::Installed(report) =
        read_status(t.path(), &ctx, &DaemonHealthClient::new()).unwrap()
    else {
        panic!("expected installed")
    };
    assert_eq!(
        report.daemon,
        json!({"sessions_active":2,"running":false,"extra":"kept"})
            .as_object()
            .unwrap()
            .clone()
    );
    let request = worker.join().unwrap();
    assert!(request.starts_with("GET /health HTTP/1.1\r\n"));
    assert!(
        request
            .lines()
            .any(|l| l.eq_ignore_ascii_case("authorization: Bearer fixture-token"))
    );
    assert_eq!(fs::read_to_string(paths.port()).unwrap(), port.to_string());
}
#[test]
fn ignores_inherited_proxy_and_redirect() {
    if std::env::var_os("KEN_PROXY_TEST_CHILD").is_none() {
        let proxy = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", proxy.local_addr().unwrap());
        let status = Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "ignores_inherited_proxy_and_redirect"])
            .env("KEN_PROXY_TEST_CHILD", "1")
            .env("http_proxy", &url)
            .env("HTTP_PROXY", &url)
            .env("https_proxy", &url)
            .env("HTTPS_PROXY", &url)
            .env("ALL_PROXY", &url)
            .env("all_proxy", &url)
            .env("NO_PROXY", "")
            .env("no_proxy", "")
            .status()
            .unwrap();
        assert!(status.success());
        proxy.set_nonblocking(true).unwrap();
        assert_eq!(
            proxy.accept().unwrap_err().kind(),
            std::io::ErrorKind::WouldBlock
        );
        return;
    }
    let (port, _, worker) = server(200, "", r#"{"ok":true}"#, false);
    let (_t, paths, _) = project(Some(port));
    assert!(
        DaemonHealthClient::new()
            .probe(&paths, &metadata())
            .unwrap()
            .is_some()
    );
    worker.join().unwrap();
    let destination = TcpListener::bind("127.0.0.1:0").unwrap();
    let (port, _, worker) = server(
        302,
        &format!(
            "Location: http://{}/ready\r\n",
            destination.local_addr().unwrap()
        ),
        "",
        false,
    );
    fs::write(paths.port(), port.to_string()).unwrap();
    assert!(
        DaemonHealthClient::new()
            .probe(&paths, &metadata())
            .unwrap()
            .is_none()
    );
    worker.join().unwrap();
    destination.set_nonblocking(true).unwrap();
    assert_eq!(
        destination.accept().unwrap_err().kind(),
        std::io::ErrorKind::WouldBlock
    );
}
#[test]
fn empty_body_or_object_is_stopped() {
    for body in ["", "{}"] {
        let (port, _, worker) = server(200, "", body, false);
        let (_t, p, _) = project(Some(port));
        assert!(
            DaemonHealthClient::new()
                .probe(&p, &metadata())
                .unwrap()
                .is_none()
        );
        worker.join().unwrap();
    }
}
#[test]
fn invalid_payload_and_http_error_are_stopped() {
    for (code, body) in [
        (200, "invalid"),
        (200, "[]"),
        (200, "null"),
        (401, "{}"),
        (500, "{}"),
        (200, "\"text\""),
    ] {
        let (port, _, worker) = server(code, "", body, false);
        let (_t, p, _) = project(Some(port));
        assert!(
            DaemonHealthClient::new()
                .probe(&p, &metadata())
                .unwrap()
                .is_none()
        );
        worker.join().unwrap();
    }
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    drop(listener);
    let (_t, p, _) = project(Some(port));
    assert!(
        DaemonHealthClient::new()
            .probe(&p, &metadata())
            .unwrap()
            .is_none()
    );
}
#[test]
fn slow_body_hits_global_deadline() {
    let (port, release, worker) = server(200, "", r#"{"ok":true}"#, true);
    let (_t, p, _) = project(Some(port));
    let started = Instant::now();
    assert!(
        DaemonHealthClient::new()
            .probe(&p, &metadata())
            .unwrap()
            .is_none()
    );
    let elapsed = started.elapsed();
    release.send(()).unwrap();
    worker.join().unwrap();
    assert!(
        elapsed >= Duration::from_millis(700) && elapsed < Duration::from_secs(3),
        "{elapsed:?}"
    );
}
#[test]
fn missing_port_does_not_require_auth_token() {
    let (_t, p, _) = project(None);
    let client = DaemonHealthClient::new();
    assert_eq!(client.probe(&p, &Map::new()).unwrap(), None);
    assert!(!p.port().exists());
    for port in ["bad", "65536", "-1", "0"] {
        fs::write(p.port(), port).unwrap();
        assert!(client.probe(&p, &Map::new()).unwrap().is_none());
    }
    fs::write(p.port(), "12345").unwrap();
    assert!(client.probe(&p, &Map::new()).is_err());
    let error = client
        .probe(&p, json!({"auth_token":["secret"]}).as_object().unwrap())
        .unwrap_err()
        .to_string();
    assert!(!error.contains("secret"));
}
