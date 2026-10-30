use ken_context::{NativeNumerics, Policy};
use ken_daemon::{
    client::{Client, ClientOptions, Program},
    server::{self, DaemonConfig},
    state::DaemonState,
};
use ken_retrieval::{Result, query_encoder::QueryEncoder};
use serde_json::json;
use std::{
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    path::Path,
    process::{Child, Command, Stdio},
    rc::Rc,
    time::{Duration, Instant},
};
struct Encoder;
impl QueryEncoder for Encoder {
    fn embed_query(&self, _: &ken_text::PythonText) -> Result<Vec<f32>> {
        Ok(vec![1., 0.])
    }
}
impl ken_retrieval::DocumentEncoder for Encoder {
    fn dim(&self) -> Result<usize> {
        Ok(2)
    }
    fn token_count(&self, text: &str) -> Result<usize> {
        Ok(text.split_whitespace().count())
    }
    fn embed_passages(&self, texts: &[&str]) -> Result<Vec<Vec<f32>>> {
        Ok(texts.iter().map(|_| vec![1., 0.]).collect())
    }
}
// The child is a Rust test process with the production state/HTTP owners; only
// its query model is injected. No Python interpreter or mocked HTTP transport.
#[test]
#[ignore]
fn daemon_process_child() {
    let Some(root) = std::env::var_os("KEN_DAEMON_TEST_ROOT") else {
        return;
    };
    let root = std::path::PathBuf::from(root);
    let mut config = DaemonConfig::new(&root);
    config.maintenance_delay = Duration::from_millis(50);
    config.idle_timeout = Duration::from_secs(30);
    config.empty_grace = Duration::from_secs(30);
    match std::env::var("KEN_DAEMON_TEST_EXPIRY").as_deref() {
        Ok("idle") => config.idle_timeout = Duration::from_millis(250),
        Ok("empty") => config.empty_grace = Duration::from_millis(250),
        _ => (),
    }
    let state = DaemonState::open(
        &root,
        Rc::new(Encoder),
        Box::new(NativeNumerics::default()),
        Policy::default(),
    )
    .unwrap();
    let grammar = std::path::PathBuf::from(
        std::env::var_os("KEN_GRAMMAR_MANIFEST")
            .expect("native process indexing requires prepared grammar manifest"),
    );
    let maintenance = ken_daemon::native::IndexResources {
        grammar_manifest: grammar,
        model: "daemon-fixture-model".into(),
        encoder: std::sync::Arc::new(Encoder),
    }
    .maintenance(&root);
    server::serve(config, state, Some(maintenance)).unwrap();
}
struct ChildGuard(Child);
impl Drop for ChildGuard {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}
fn installed() -> tempfile::TempDir {
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir(root.path().join(".ken")).unwrap();
    std::fs::write(
        root.path().join(".ken/meta.json"),
        br#"{"project_id":"process-test","auth_token":"correct-token"}"#,
    )
    .unwrap();
    root
}
fn start(root: &Path) -> ChildGuard {
    ChildGuard(
        Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "daemon_process_child",
                "--ignored",
                "--nocapture",
            ])
            .env("KEN_DAEMON_TEST_ROOT", root)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::inherit())
            .spawn()
            .unwrap(),
    )
}
fn port(root: &Path) -> u16 {
    let deadline = Instant::now() + Duration::from_secs(10);
    while Instant::now() < deadline {
        if let Ok(text) = std::fs::read_to_string(root.join(".ken/daemon.port"))
            && let Ok(port) = text.parse()
        {
            return port;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    panic!("native daemon failed to advertise port");
}
fn raw(port: u16, request: &str) -> String {
    let mut stream = TcpStream::connect(("127.0.0.1", port)).unwrap();
    stream
        .set_read_timeout(Some(Duration::from_secs(5)))
        .unwrap();
    stream.write_all(request.as_bytes()).unwrap();
    let mut response = String::new();
    stream.read_to_string(&mut response).unwrap();
    response
}
fn client(root: &Path) -> Client {
    Client::new(
        root,
        Program::new(std::env::current_exe().unwrap()),
        ClientOptions::default(),
    )
}
#[test]
fn native_process_serves_authenticated_sessions_and_cleans_runtime_files_after_joined_shutdown() {
    let root = installed();
    let mut child = start(root.path());
    let port = port(root.path());
    assert!(root.path().join(".ken/daemon.pid").is_file());
    assert!(
        raw(
            port,
            "GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        )
        .starts_with("HTTP/1.1 401")
    );
    let client = client(root.path());
    assert_eq!(client.health().unwrap()["project_id"], "process-test");
    let first = client
        .post("/sessions/start", &json!({"session_id":"process"}))
        .unwrap()
        .unwrap();
    assert_eq!(
        client
            .post("/sessions/start", &json!({"session_id":"process"}))
            .unwrap()
            .unwrap()["ken_session_pk"],
        first["ken_session_pk"]
    );
    assert_eq!(client.health().unwrap()["sessions_active"], 1);
    client
        .post(
            "/tools/pre",
            &json!({"session_id":"process","tool":"Edit","input":{"path":"x.rs"}}),
        )
        .unwrap()
        .unwrap();
    client.post("/shutdown", &json!({})).unwrap().unwrap();
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        if let Some(status) = child.0.try_wait().unwrap() {
            assert!(status.success());
            break;
        }
        assert!(
            Instant::now() < deadline,
            "native process did not join workers"
        );
        std::thread::sleep(Duration::from_millis(20));
    }
    assert!(!root.path().join(".ken/daemon.port").exists());
    assert!(!root.path().join(".ken/daemon.pid").exists());
    let db = rusqlite::Connection::open(root.path().join(".ken/ken.db")).unwrap();
    let ended: i64 = db
        .query_row(
            "SELECT count(*) FROM cr_sessions WHERE ended_at IS NOT NULL",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(ended, 1);
}
#[test]
fn malformed_http_and_disconnected_clients_do_not_kill_service_or_run_without_auth() {
    let root = installed();
    let _child = start(root.path());
    let port = port(root.path());
    for (request, status) in [
        (
            "POST /sessions/start HTTP/1.1\r\nAuthorization: Bearer correct-token\r\nContent-Length: 1\r\n\r\n{",
            400,
        ),
        (
            "POST /sessions/start HTTP/1.1\r\nAuthorization: Bearer correct-token\r\nContent-Length: 2\r\n\r\n{}",
            400,
        ),
        (
            "GET /unknown HTTP/1.1\r\nAuthorization: Bearer correct-token\r\n\r\n",
            404,
        ),
        (
            "POST /prompts HTTP/1.1\r\nAuthorization: Bearer correct-token\r\nContent-Length: 9999999999\r\n\r\n",
            413,
        ),
    ] {
        assert!(raw(port, request).starts_with(&format!("HTTP/1.1 {status}")));
    }
    let mut disconnected = TcpStream::connect(("127.0.0.1", port)).unwrap();
    disconnected
        .write_all(b"GET /health HTTP/1.1\r\nAuthorization: Bearer correct-token\r\n\r\n")
        .unwrap();
    drop(disconnected);
    assert_eq!(client(root.path()).health().unwrap()["ok"], true);
    client(root.path())
        .post("/shutdown", &json!({}))
        .unwrap()
        .unwrap();
}
#[test]
fn accepted_read_timeout_preserves_port_and_does_not_spawn_a_second_process() {
    let root = installed();
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let port = listener.local_addr().unwrap().port();
    std::fs::write(root.path().join(".ken/daemon.port"), port.to_string()).unwrap();
    let worker = std::thread::spawn(move || {
        let (mut socket, _) = listener.accept().unwrap();
        let mut bytes = [0; 4096];
        let _ = socket.read(&mut bytes);
        std::thread::sleep(Duration::from_millis(250));
    });
    let options = ClientOptions {
        rank_timeout: Duration::from_millis(30),
        ..Default::default()
    };
    let client = Client::new(
        root.path(),
        Program::new(root.path().join("must-not-spawn")),
        options,
    );
    assert!(
        client
            .post("/rank", &json!({"query":"slow"}))
            .unwrap()
            .is_none()
    );
    assert_eq!(
        std::fs::read_to_string(root.path().join(".ken/daemon.port")).unwrap(),
        port.to_string()
    );
    worker.join().unwrap();
}
#[test]
fn stale_port_spawns_one_native_child_with_project_environment_and_health_handshake() {
    let root = installed();
    let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let stale = listener.local_addr().unwrap().port();
    drop(listener);
    std::fs::write(root.path().join(".ken/daemon.port"), stale.to_string()).unwrap();
    let mut program = Program::new(std::env::current_exe().unwrap());
    program.arguments = vec![
        "--exact".into(),
        "daemon_process_child".into(),
        "--ignored".into(),
        "--nocapture".into(),
    ];
    program
        .environment
        .insert("KEN_DAEMON_TEST_ROOT".into(), root.path().into());
    let client = Client::new(root.path(), program, ClientOptions::default());
    let response = client
        .post("/sessions/start", &json!({"session_id":"spawned"}))
        .unwrap()
        .unwrap();
    assert_eq!(response["ok"], true);
    assert_ne!(port(root.path()), stale);
    client.post("/shutdown", &json!({})).unwrap().unwrap();
}

#[test]
fn real_process_warm_resync_and_watcher_use_native_indexer_on_dedicated_storage_connection() {
    let root = installed();
    std::fs::write(
        root.path().join("before.py"),
        "def before():\n    return 1\n",
    )
    .unwrap();
    let _child = start(root.path());
    let _port = port(root.path());
    let deadline = Instant::now() + Duration::from_secs(15);
    loop {
        let response = client(root.path())
            .post("/file/symbols", &json!({"path":"before.py"}))
            .unwrap()
            .unwrap();
        if response["ok"] == true {
            break;
        }
        assert!(
            Instant::now() < deadline,
            "warm native indexing did not complete: {response}"
        );
        std::thread::sleep(Duration::from_millis(50));
    }
    std::fs::write(root.path().join("after.py"), "def after():\n    return 2\n").unwrap();
    let deadline = Instant::now() + Duration::from_secs(15);
    loop {
        let response = client(root.path())
            .post("/file/symbols", &json!({"path":"after.py"}))
            .unwrap()
            .unwrap();
        if response["ok"] == true {
            break;
        }
        assert!(
            Instant::now() < deadline,
            "watcher native indexing did not complete"
        );
        std::thread::sleep(Duration::from_millis(50));
    }
    std::fs::remove_file(root.path().join("before.py")).unwrap();
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        let response = client(root.path())
            .post("/file/symbols", &json!({"path":"before.py"}))
            .unwrap()
            .unwrap();
        if response["ok"] == false {
            break;
        }
        assert!(Instant::now() < deadline, "watcher deletion not applied");
        std::thread::sleep(Duration::from_millis(50));
    }
    client(root.path())
        .post("/shutdown", &json!({}))
        .unwrap()
        .unwrap();
}

#[test]
fn zero_session_grace_and_idle_deadline_finalize_and_remove_advertisement() {
    for mode in ["empty", "idle"] {
        let root = installed();
        let mut command = Command::new(std::env::current_exe().unwrap());
        command
            .args([
                "--exact",
                "daemon_process_child",
                "--ignored",
                "--nocapture",
            ])
            .env("KEN_DAEMON_TEST_ROOT", root.path())
            .env("KEN_DAEMON_TEST_EXPIRY", mode)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::inherit());
        let mut child = ChildGuard(command.spawn().unwrap());
        let _ = port(root.path());
        if mode == "empty" {
            let client = client(root.path());
            client
                .post("/sessions/start", &json!({"session_id":"expiry"}))
                .unwrap()
                .unwrap();
            client
                .post("/sessions/end", &json!({"session_id":"expiry"}))
                .unwrap()
                .unwrap();
        }
        let deadline = Instant::now() + Duration::from_secs(10);
        loop {
            if let Some(status) = child.0.try_wait().unwrap() {
                assert!(status.success());
                break;
            }
            assert!(
                Instant::now() < deadline,
                "{mode} shutdown did not complete"
            );
            std::thread::sleep(Duration::from_millis(20));
        }
        assert!(!root.path().join(".ken/daemon.port").exists());
    }
}
