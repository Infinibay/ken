//! Native protocol contracts; no Python server, model, or accepted matrix replay.
use ken_cli::mcp::{ToolHandler, serve_transport};
use ken_query::execution::Cancellation;
use serde_json::{Value, json, value::RawValue};
use std::{
    collections::BTreeMap,
    io::{BufRead, BufReader, Read, Write},
    os::unix::net::UnixStream,
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
        mpsc,
    },
    thread,
    time::{Duration, Instant},
};
fn init(id: Value, version: &str) -> Value {
    json!({"jsonrpc":"2.0","id":id,"method":"initialize","params":{"protocolVersion":version,"capabilities":{},"clientInfo":{"name":"native-protocol-tests","version":"1"}}})
}
fn meta(version: &str) -> Value {
    json!({"io.modelcontextprotocol/protocolVersion":version,"io.modelcontextprotocol/clientCapabilities":{}})
}
fn send(out: &mut impl Write, value: &Value) {
    writeln!(out, "{value}").unwrap();
    out.flush().unwrap();
}
fn receive(input: &mut impl BufRead) -> Value {
    let mut line = String::new();
    assert!(
        input.read_line(&mut line).unwrap() > 0,
        "expected protocol response"
    );
    serde_json::from_str(&line).unwrap()
}
struct Process {
    child: Child,
    input: Option<ChildStdin>,
    responses: mpsc::Receiver<Value>,
    reader: Option<thread::JoinHandle<()>>,
    _root: tempfile::TempDir,
}
impl Process {
    fn start() -> Self {
        let root = tempfile::tempdir().unwrap();
        std::fs::create_dir(root.path().join(".ken")).unwrap();
        std::fs::write(root.path().join(".ken/meta.json"), "{}").unwrap();
        let mut db = ken_store::ProjectDatabase::open(&root.path().join(".ken/ken.db")).unwrap();
        db.initialize().unwrap();
        drop(db);
        let manifest = root.path().join("installation.json");
        let grammar = std::env::var_os("KEN_GRAMMAR_MANIFEST").expect("prepared native grammars");
        std::fs::write(&manifest,serde_json::to_vec(&json!({"format":"ken-search-installation/1","grammar_manifest":PathBuf::from(grammar)})).unwrap()).unwrap();
        let mut child = Command::new(env!("CARGO_BIN_EXE_ken-rs"))
            .arg("--resources")
            .arg(manifest)
            .arg("mcp")
            .arg(root.path())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .unwrap();
        let input = child.stdin.take();
        let output = child.stdout.take().unwrap();
        let (tx, responses) = mpsc::channel();
        let reader = thread::spawn(move || {
            let mut input = BufReader::new(output);
            loop {
                let mut line = String::new();
                if input.read_line(&mut line).unwrap_or(0) == 0 {
                    break;
                }
                let response = serde_json::from_str(&line).unwrap();
                if tx.send(response).is_err() {
                    break;
                }
            }
        });
        Self {
            child,
            input,
            responses,
            reader: Some(reader),
            _root: root,
        }
    }
    fn send(&mut self, value: &Value) {
        send(self.input.as_mut().unwrap(), value)
    }
    fn receive(&self) -> Value {
        self.responses
            .recv_timeout(Duration::from_secs(10))
            .expect("native MCP response before deadline")
    }
    fn initialize(&mut self, version: &str) -> Value {
        self.send(&init(json!("init"), version));
        let response = self.receive();
        self.send(&json!({"jsonrpc":"2.0","method":"notifications/initialized"}));
        response
    }
    fn finish(mut self) {
        self.input.take();
        let deadline = Instant::now() + Duration::from_secs(10);
        loop {
            if let Some(status) = self.child.try_wait().unwrap() {
                assert!(status.success());
                break;
            }
            assert!(Instant::now() < deadline, "EOF failed to close MCP");
            thread::yield_now();
        }
        self.reader.take().unwrap().join().unwrap();
        assert!(
            self.responses.try_recv().is_err(),
            "unsolicited late response"
        );
    }
}
impl Drop for Process {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        if let Some(reader) = self.reader.take() {
            let _ = reader.join();
        }
    }
}
#[test]
fn all_frozen_handshake_versions_negotiate_and_unknown_dates_counteroffer_handshake_latest() {
    for requested in [
        "2024-11-05",
        "2025-03-26",
        "2025-06-18",
        "2025-11-25",
        "unknown-version",
        "2026-07-28",
    ] {
        let mut process = Process::start();
        let response = process.initialize(requested);
        assert_eq!(
            response["result"]["protocolVersion"],
            if ["unknown-version", "2026-07-28"].contains(&requested) {
                "2025-11-25"
            } else {
                requested
            }
        );
        process.send(&json!({"jsonrpc":"2.0","id":2,"method":"ping"}));
        assert_eq!(process.receive()["result"], json!({}));
        process.finish();
    }
}
#[test]
fn modern_envelope_discovery_is_frozen_sdk_behavior_and_mixed_eras_are_rejected() {
    let mut process = Process::start();
    process.send(&json!({"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":meta("2026-07-28")}}));
    let response = process.receive();
    assert_eq!(
        response["result"]["supportedVersions"],
        json!(["2026-07-28"])
    );
    assert_eq!(response["result"]["resultType"], "complete");
    assert_eq!(response["result"]["ttlMs"], 0);
    assert_eq!(response["result"]["cacheScope"], "private");
    assert!(response["result"]["_meta"]["io.modelcontextprotocol/serverInfo"].is_object());
    process.send(&json!({"jsonrpc":"2.0","id":"modern-ping","method":"ping","params":{"_meta":meta("2026-07-28")}}));
    assert_eq!(process.receive()["error"]["code"], -32601);
    process.send(&init(json!(2), "2025-11-25"));
    assert_eq!(process.receive()["error"]["code"], -32022);
    process.finish();
    let mut process = Process::start();
    process.initialize("2025-11-25");
    process.send(&json!({"jsonrpc":"2.0","id":3,"method":"tools/list","params":{"_meta":meta("2026-07-28")}}));
    assert_eq!(process.receive()["error"]["code"], -32600);
    process.finish();
    let mut process = Process::start();
    process.send(&json!({"jsonrpc":"2.0","id":4,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}));
    assert_eq!(process.receive()["error"]["code"], -32602);
    process.finish();
}
#[test]
fn all_thirteen_tools_are_listed_and_real_native_calls_preserve_lossless_payloads() {
    let mut process = Process::start();
    process.initialize("2025-06-18");
    process.send(&json!({"jsonrpc":"2.0","id":2,"method":"tools/list"}));
    let response = process.receive();
    let tools = response["result"]["tools"].as_array().unwrap();
    let mut names = tools
        .iter()
        .map(|t| {
            assert_eq!(t["inputSchema"]["type"], "object");
            assert!(t["inputSchema"]["properties"].is_object());
            t["name"].as_str().unwrap().to_owned()
        })
        .collect::<Vec<_>>();
    names.sort();
    assert_eq!(
        names,
        [
            "ken_calculate",
            "ken_check",
            "ken_find",
            "ken_query",
            "ken_rank",
            "ken_read",
            "ken_reason",
            "ken_reason_record",
            "ken_recall",
            "ken_related",
            "ken_remember",
            "ken_rule",
            "ken_who"
        ]
    );
    let integer = format!("1{}", "0".repeat(499));
    process.send(&json!({"jsonrpc":"2.0","id":"large","method":"tools/call","params":{"name":"ken_calculate","arguments":{"expression":"(10**16)**16*(10**16)**15*1000","output_format":"json"}}}));
    let answer = process.receive();
    assert_eq!(answer["result"]["isError"], false);
    assert!(
        answer["result"]["content"][0]["text"]
            .as_str()
            .unwrap()
            .contains(&integer)
    );
    let query = r#"language "kql/2";module lossless_mcp;query q{select "\ud800";}"#;
    process.send(&json!({"jsonrpc":"2.0","id":"surrogate","method":"tools/call","params":{"name":"ken_find","arguments":{"scope":"structure","query_language":"kql/2","query":query,"full":true}}}));
    let answer = process.receive();
    assert_eq!(answer["result"]["isError"], false, "{answer}");
    assert!(
        answer["result"]["content"][0]["text"]
            .as_str()
            .unwrap()
            .contains("\\ud800")
    );
    process.finish();
}
#[test]
fn bounded_framing_recovers_after_oversize_and_unknown_notifications_do_not_produce_responses() {
    let mut process = Process::start();
    process.initialize("2025-11-25");
    for _ in 0..1000 {
        process.send(&json!({"jsonrpc":"2.0","method":"notifications/unknown","params":{}}));
    }
    let input = process.input.as_mut().unwrap();
    input.write_all(&vec![b' '; 8 * 1024 * 1024 + 1]).unwrap();
    input.write_all(b"\n").unwrap();
    input.flush().unwrap();
    assert_eq!(process.receive()["error"]["code"], -32700);
    process.send(&json!({"jsonrpc":"2.0","id":"healthy","method":"ping"}));
    assert_eq!(process.receive()["id"], "healthy");
    process.finish();
}
struct QueryHandler {
    root: PathBuf,
    ready: mpsc::SyncSender<()>,
    cancelled: Arc<AtomicBool>,
}
impl ToolHandler for QueryHandler {
    fn definitions(&self) -> Vec<Value> {
        vec![json!({"name":"actual_query","inputSchema":{"type":"object","properties":{}}})]
    }
    fn call(
        &mut self,
        _: &str,
        _: &RawValue,
        cancellation: Cancellation,
    ) -> Result<String, String> {
        use ken_structural::application::sessions::{
            QueryApplication, QueryOptions, QueryPhase, SessionOptions,
        };
        let grammar = std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap();
        let catalog = Arc::new(ken_syntax::GrammarCatalog::prepared(Path::new(&grammar)).unwrap());
        let app = QueryApplication::new(&self.root, catalog, BTreeMap::new()).unwrap();
        let mut session = app
            .open_transient(SessionOptions {
                cache_mb: 0.,
                ..Default::default()
            })
            .unwrap();
        let ready = self.ready.clone();
        let options = QueryOptions {
            timeout_ms: Some(2500.),
            cancellation,
            observer: Some(Arc::new(move |phase| {
                if phase == QueryPhase::Query {
                    let _ = ready.send(());
                }
            })),
            ..Default::default()
        };
        let result=session.search_json(Some(r#"language "kql/2";module transport_cancel;query q{callable $a {} callable $b {} callable $c {} select $a,$b,$c;}"#),options);
        let _ = session.close();
        let text = match result {
            Ok(text) => text,
            Err(error) => error.to_string(),
        };
        if !text.contains("cancelled") {
            eprintln!("actual query transport did not reach cancellation: {text}");
        }
        self.cancelled
            .store(text.contains("cancelled"), Ordering::SeqCst);
        Ok(text)
    }
}
fn query_fixture() -> tempfile::TempDir {
    let root = tempfile::tempdir().unwrap();
    let source = (0..250)
        .map(|i| format!("def f{i}():\n return {i}\n"))
        .collect::<String>();
    std::fs::write(root.path().join("source.py"), source).unwrap();
    root
}
#[test]
fn cancellation_arriving_during_actual_query_interrupts_and_suppresses_its_late_reply() {
    let root = query_fixture();
    let (input, mut host_write) = UnixStream::pair().unwrap();
    let (output, host_read) = UnixStream::pair().unwrap();
    host_read
        .set_read_timeout(Some(Duration::from_secs(8)))
        .unwrap();
    let (ready_tx, ready_rx) = mpsc::sync_channel(0);
    let cancelled = Arc::new(AtomicBool::new(false));
    let mut handler = QueryHandler {
        root: root.path().into(),
        ready: ready_tx,
        cancelled: cancelled.clone(),
    };
    let host = thread::spawn(move || {
        let mut read = BufReader::new(host_read);
        send(&mut host_write, &init(json!(1), "2025-11-25"));
        receive(&mut read);
        send(
            &mut host_write,
            &json!({"jsonrpc":"2.0","method":"notifications/initialized"}),
        );
        send(
            &mut host_write,
            &json!({"jsonrpc":"2.0","id":"work","method":"tools/call","params":{"name":"actual_query","arguments":{}}}),
        );
        ready_rx.recv_timeout(Duration::from_secs(8)).unwrap();
        send(
            &mut host_write,
            &json!({"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":"work","reason":"test cancellation"}}),
        );
        send(
            &mut host_write,
            &json!({"jsonrpc":"2.0","id":"after","method":"ping"}),
        );
        assert_eq!(
            receive(&mut read)["id"],
            "after",
            "cancelled query must not emit late result/error"
        );
        drop(host_write);
        let mut tail = String::new();
        read.read_to_string(&mut tail).unwrap();
        assert!(tail.is_empty());
    });
    serve_transport(input, output, &mut handler).unwrap();
    host.join().unwrap();
    assert!(
        cancelled.load(Ordering::SeqCst),
        "actual native query observed cancellation, not timeout"
    );
}
#[test]
fn eof_cancels_active_query_and_joins_reader_without_waiting_for_more_input() {
    let root = query_fixture();
    let (input, mut host_write) = UnixStream::pair().unwrap();
    let (output, mut host_read) = UnixStream::pair().unwrap();
    host_read
        .set_read_timeout(Some(Duration::from_secs(8)))
        .unwrap();
    let (ready_tx, ready_rx) = mpsc::sync_channel(0);
    let cancelled = Arc::new(AtomicBool::new(false));
    let mut handler = QueryHandler {
        root: root.path().into(),
        ready: ready_tx,
        cancelled: cancelled.clone(),
    };
    let host = thread::spawn(move || {
        let mut read = BufReader::new(&mut host_read);
        send(&mut host_write, &init(json!(1), "2025-11-25"));
        receive(&mut read);
        send(
            &mut host_write,
            &json!({"jsonrpc":"2.0","method":"notifications/initialized"}),
        );
        send(
            &mut host_write,
            &json!({"jsonrpc":"2.0","id":99,"method":"tools/call","params":{"name":"actual_query","arguments":{}}}),
        );
        ready_rx.recv_timeout(Duration::from_secs(8)).unwrap();
        drop(host_write);
        let mut tail = String::new();
        read.read_to_string(&mut tail).unwrap();
        assert!(tail.is_empty());
    });
    let started = Instant::now();
    serve_transport(input, output, &mut handler).unwrap();
    host.join().unwrap();
    assert!(started.elapsed() < Duration::from_secs(8));
    assert!(cancelled.load(Ordering::SeqCst));
}

struct CheckHandler {
    root: PathBuf,
    owner: mpsc::SyncSender<i32>,
    cancelled: Arc<AtomicBool>,
}
impl ToolHandler for CheckHandler {
    fn definitions(&self) -> Vec<Value> {
        vec![json!({"name":"actual_check","inputSchema":{"type":"object","properties":{}}})]
    }
    fn call(
        &mut self,
        _: &str,
        _: &RawValue,
        cancellation: Cancellation,
    ) -> Result<String, String> {
        use ken_checks_application::{ChecksApplication, Resources, WorkerControl, WorkerProgram};
        let worker = std::env::var_os("KEN_CHECK_WORKER")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                PathBuf::from(env!("CARGO_BIN_EXE_ken-rs")).with_file_name("ken-check-worker")
            });
        assert!(
            worker.is_file(),
            "real native check worker must be built: {}",
            worker.display()
        );
        let grammar = std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap();
        let resources =
            Resources::prepared(Path::new(&grammar), WorkerProgram::new(worker)).unwrap();
        let application = ChecksApplication::new(&self.root, resources).unwrap();
        let request=ken_contracts::checks::QueryRequest{root:self.root.clone(),source:r#"language "kql/2";module transport_check_cancel;query q{callable $a {} callable $b {} callable $c {} select $a,$b,$c;}"#.into(),query_name:None,libraries:BTreeMap::new(),path:".".into(),source_paths:None,timeout_ms:Some(2500.),max_states:Some(u64::MAX),max_rows:None,source_profile:"full".into()};
        self.owner
            .send(unsafe { libc::syscall(libc::SYS_gettid) } as i32)
            .unwrap();
        let observed = application
            .observe(
                &request,
                &WorkerControl {
                    cancellation,
                    deadline: None,
                },
            )
            .unwrap();
        let text = serde_json::to_string(&observed).unwrap();
        self.cancelled
            .store(text.contains("cancelled"), Ordering::SeqCst);
        Ok(text)
    }
}
#[test]
fn cancellation_reaches_actual_native_check_worker_and_reaps_before_next_reply() {
    let root = query_fixture();
    let (input, mut host_write) = UnixStream::pair().unwrap();
    let (output, host_read) = UnixStream::pair().unwrap();
    host_read
        .set_read_timeout(Some(Duration::from_secs(8)))
        .unwrap();
    let (owner_tx, owner_rx) = mpsc::sync_channel(0);
    let cancelled = Arc::new(AtomicBool::new(false));
    let mut handler = CheckHandler {
        root: root.path().into(),
        owner: owner_tx,
        cancelled: cancelled.clone(),
    };
    let host = thread::spawn(move || {
        let mut read = BufReader::new(host_read);
        send(&mut host_write, &init(json!(1), "2025-11-25"));
        receive(&mut read);
        send(
            &mut host_write,
            &json!({"jsonrpc":"2.0","method":"notifications/initialized"}),
        );
        send(
            &mut host_write,
            &json!({"jsonrpc":"2.0","id":"check","method":"tools/call","params":{"name":"actual_check","arguments":{}}}),
        );
        let owner = owner_rx.recv_timeout(Duration::from_secs(8)).unwrap();
        let children = format!("/proc/{}/task/{owner}/children", std::process::id());
        let deadline = Instant::now() + Duration::from_secs(5);
        let pid = loop {
            if let Some(pid) = std::fs::read_to_string(&children).ok().and_then(|s| {
                s.split_whitespace()
                    .next()
                    .and_then(|s| s.parse::<u32>().ok())
            }) {
                break pid;
            }
            assert!(
                Instant::now() < deadline,
                "native check worker did not start"
            );
            thread::yield_now();
        };
        send(
            &mut host_write,
            &json!({"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":"check"}}),
        );
        send(
            &mut host_write,
            &json!({"jsonrpc":"2.0","id":"after-check","method":"ping"}),
        );
        assert_eq!(receive(&mut read)["id"], "after-check");
        assert!(
            !Path::new(&format!("/proc/{pid}")).exists(),
            "native check worker must be reaped before serving next response"
        );
        drop(host_write);
    });
    serve_transport(input, output, &mut handler).unwrap();
    host.join().unwrap();
    assert!(
        cancelled.load(Ordering::SeqCst),
        "check supervisor observed cancellation rather than timeout"
    );
}
