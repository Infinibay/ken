//! Bounded loopback HTTP. The caller thread exclusively owns request state.
use crate::runtime::RuntimeFiles;
use crate::{
    Error, Result,
    queue::{BatchIndexer, IndexQueue, QueueOptions},
    state::DaemonState,
    watcher::FileWatcher,
};
use serde_json::{Value, json};
use std::{
    io::{Read, Write},
    net::{TcpListener, TcpStream},
    path::{Path, PathBuf},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
        mpsc,
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};
#[derive(Clone, Debug)]
pub struct DaemonConfig {
    pub root: PathBuf,
    pub idle_timeout: Duration,
    pub empty_grace: Duration,
    pub maintenance_delay: Duration,
    pub header_timeout: Duration,
    pub max_body_bytes: usize,
    pub max_connections: usize,
}
impl DaemonConfig {
    pub fn new(root: &Path) -> Self {
        Self {
            root: root.into(),
            idle_timeout: Duration::from_secs(600),
            empty_grace: Duration::from_secs(60),
            maintenance_delay: Duration::from_secs(2),
            header_timeout: Duration::from_secs(5),
            max_body_bytes: 8 * 1024 * 1024,
            max_connections: 64,
        }
    }
}
pub struct Maintenance {
    pub factory: Box<dyn FnOnce() -> Result<Box<dyn BatchIndexer>> + Send>,
}
struct Metrics {
    project: String,
    active: usize,
    started: Instant,
    activity: Instant,
}
impl Metrics {
    fn from(state: &DaemonState) -> Self {
        Self {
            project: state.project_id.clone(),
            active: state.active_sessions(),
            started: state.started,
            activity: state.last_activity,
        }
    }
    fn payload(&self) -> Value {
        let tenth = |elapsed: Duration| (elapsed.as_secs_f64() * 10.).round() / 10.;
        json!({"ok":true,"project_id":self.project,"sessions_active":self.active,"uptime_s":tenth(self.started.elapsed()),"idle_s":tenth(self.activity.elapsed())})
    }
}
struct Request {
    path: String,
    payload: Value,
    reply: mpsc::Sender<(u16, Value)>,
}
pub fn serve(
    mut config: DaemonConfig,
    mut state: DaemonState,
    maintenance: Option<Maintenance>,
) -> Result<()> {
    config.root = config.root.canonicalize()?;
    if config.root != state.paths().root() {
        return Err(Error::Invalid(
            "daemon state/config project mismatch".into(),
        ));
    }
    if config.max_connections == 0 || config.max_body_bytes == 0 {
        return Err(Error::Invalid("daemon bounds must be positive".into()));
    }
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    listener.set_nonblocking(true)?;
    let port = listener.local_addr()?.port();
    let _files = RuntimeFiles::publish(&config.root, port)?;
    let stop = Arc::new(AtomicBool::new(false));
    let metrics = Arc::new(Mutex::new(Metrics::from(&state)));
    let (tx, rx) = mpsc::sync_channel(64);
    let net_stop = stop.clone();
    let net_metrics = metrics.clone();
    let net_config = config.clone();
    let token = state.auth_token.clone();
    let network = thread::Builder::new()
        .name("ken-http".into())
        .spawn(move || accept(listener, tx, net_stop, net_metrics, &token, &net_config))?;
    let background = if let Some(maintenance) = maintenance {
        let background_stop = stop.clone();
        let root = config.root.clone();
        let delay = config.maintenance_delay;
        Some(
            match thread::Builder::new()
                .name("ken-maintenance".into())
                .spawn(move || {
                    let stop = background_stop;
                    let deadline = Instant::now() + delay;
                    while Instant::now() < deadline {
                        if stop.load(Ordering::Acquire) {
                            return;
                        }
                        thread::sleep(Duration::from_millis(20));
                    }
                    if stop.load(Ordering::Acquire) {
                        return;
                    }
                    match IndexQueue::start(maintenance.factory, QueueOptions::default()) {
                        Ok(queue) => {
                            if stop.load(Ordering::Acquire) {
                                let _ = queue.stop();
                                return;
                            }
                            let mut watcher = match FileWatcher::start(&root, queue.sender()) {
                                Ok(w) => Some(w),
                                Err(e) => {
                                    eprintln!("ken source watcher failed: {e}");
                                    None
                                }
                            };
                            let _ = queue.sender().resync();
                            while !stop.load(Ordering::Acquire) {
                                thread::sleep(Duration::from_millis(20));
                            }
                            if let Some(watcher) = &mut watcher
                                && let Err(e) = watcher.stop()
                            {
                                eprintln!("ken watcher close failed: {e}");
                            }
                            if let Err(e) = queue.stop() {
                                eprintln!("ken index queue close failed: {e}");
                            }
                        }
                        Err(e) => eprintln!("ken index maintenance startup failed: {e}"),
                    }
                }) {
                Ok(worker) => worker,
                Err(error) => {
                    stop.store(true, Ordering::Release);
                    let _ = network.join();
                    return Err(error.into());
                }
            },
        )
    } else {
        None
    };
    while !stop.load(Ordering::Acquire) {
        match rx.recv_timeout(Duration::from_millis(50)) {
            Ok(request) => {
                let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    state.handle(&request.path, request.payload)
                }));
                let response = match result {
                    Ok(Ok(value)) => (200, value),
                    Ok(Err(Error::Missing(field))) => {
                        (400, json!({"error":format!("missing field: {field}")}))
                    }
                    Ok(Err(Error::NotFound)) => (404, json!({"error":"not found"})),
                    Ok(Err(error)) => {
                        eprintln!("ken handler failed: {error}");
                        (500, json!({"error":"internal"}))
                    }
                    Err(_) => (500, json!({"error":"internal"})),
                };
                *metrics.lock().unwrap_or_else(|e| e.into_inner()) = Metrics::from(&state);
                let _ = request.reply.send(response);
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                stop.store(true, Ordering::Release);
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {}
        }
        if state.last_activity.elapsed() >= config.idle_timeout
            || state
                .empty_since
                .is_some_and(|since| since.elapsed() >= config.empty_grace)
        {
            stop.store(true, Ordering::Release);
        }
    }
    stop.store(true, Ordering::Release);
    let mut first = state.close_checks().err();
    if let Some(background) = background
        && background.join().is_err()
    {
        first = Some(Error::Invalid("maintenance worker panicked".into()));
    }
    if let Err(error) = state.finalize() {
        first = Some(error);
    }
    if network.join().is_err() && first.is_none() {
        first = Some(Error::Invalid("HTTP owner panicked".into()));
    }
    drop(state);
    first.map_or(Ok(()), Err)
}
fn accept(
    listener: TcpListener,
    tx: mpsc::SyncSender<Request>,
    stop: Arc<AtomicBool>,
    metrics: Arc<Mutex<Metrics>>,
    token: &str,
    config: &DaemonConfig,
) {
    let mut workers: Vec<JoinHandle<()>> = Vec::new();
    while !stop.load(Ordering::Acquire) {
        let mut i = 0;
        while i < workers.len() {
            if workers[i].is_finished() {
                let worker = workers.swap_remove(i);
                let _ = worker.join();
            } else {
                i += 1;
            }
        }
        match listener.accept() {
            Ok((mut stream, address)) => {
                if !address.ip().is_loopback() {
                    continue;
                }
                if workers.len() >= config.max_connections {
                    respond(&mut stream, 503, &json!({"error":"busy"}));
                    continue;
                }
                let tx = tx.clone();
                let stop = stop.clone();
                let metrics = metrics.clone();
                let token = token.to_owned();
                let config = config.clone();
                match thread::Builder::new()
                    .name("ken-http-request".into())
                    .spawn(move || connection(stream, tx, stop, metrics, &token, &config))
                {
                    Ok(worker) => workers.push(worker),
                    Err(e) => eprintln!("ken request worker failed: {e}"),
                }
            }
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                thread::sleep(Duration::from_millis(10))
            }
            Err(e) => {
                eprintln!("ken listener failed: {e}");
                stop.store(true, Ordering::Release);
            }
        }
    }
    drop(listener);
    for worker in workers {
        let _ = worker.join();
    }
}
fn connection(
    mut stream: TcpStream,
    tx: mpsc::SyncSender<Request>,
    stop: Arc<AtomicBool>,
    metrics: Arc<Mutex<Metrics>>,
    token: &str,
    config: &DaemonConfig,
) {
    let _ = stream.set_read_timeout(Some(Duration::from_millis(100)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(3)));
    let request = match read_request(&mut stream, &stop, config, token) {
        Ok(request) => request,
        Err((status, message)) => {
            respond(&mut stream, status, &json!({"error":message}));
            return;
        }
    };
    if request.authorization != format!("Bearer {token}") {
        respond(&mut stream, 401, &json!({"error":"unauthorised"}));
        return;
    }
    if request.method == "GET" {
        let (status, value) = if request.path == "/health" {
            (
                200,
                metrics.lock().unwrap_or_else(|e| e.into_inner()).payload(),
            )
        } else {
            (404, json!({"error":"not found"}))
        };
        respond(&mut stream, status, &value);
        return;
    }
    if request.method != "POST" {
        respond(&mut stream, 405, &json!({"error":"method not allowed"}));
        return;
    }
    let payload = if request.body.is_empty() {
        json!({})
    } else {
        match serde_json::from_slice::<Value>(&request.body) {
            Ok(value) if value.is_object() => value,
            Ok(_) => {
                respond(
                    &mut stream,
                    400,
                    &json!({"error":"bad json: expected object"}),
                );
                return;
            }
            Err(error) => {
                respond(
                    &mut stream,
                    400,
                    &json!({"error":format!("bad json: {error}")}),
                );
                return;
            }
        }
    };
    if request.path == "/shutdown" {
        respond(&mut stream, 200, &json!({"ok":true}));
        stop.store(true, Ordering::Release);
        return;
    }
    let (reply, receive) = mpsc::channel();
    let event = Request {
        path: request.path,
        payload,
        reply,
    };
    if tx.try_send(event).is_err() {
        respond(&mut stream, 503, &json!({"error":"busy"}));
        return;
    }
    loop {
        match receive.recv_timeout(Duration::from_millis(100)) {
            Ok((status, value)) => {
                respond(&mut stream, status, &value);
                return;
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => return,
            Err(mpsc::RecvTimeoutError::Timeout) => {
                if stop.load(Ordering::Acquire) {
                    return;
                }
            }
        }
    }
}
struct HttpRequest {
    method: String,
    path: String,
    authorization: String,
    body: Vec<u8>,
}
fn read_request(
    stream: &mut TcpStream,
    stop: &AtomicBool,
    config: &DaemonConfig,
    token: &str,
) -> std::result::Result<HttpRequest, (u16, String)> {
    let deadline = Instant::now() + config.header_timeout;
    let mut bytes = Vec::new();
    let mut chunk = [0u8; 4096];
    let split = loop {
        if stop.load(Ordering::Acquire) {
            return Err((503, "closing".into()));
        }
        if Instant::now() >= deadline {
            return Err((408, "request timed out".into()));
        }
        if let Some(index) = bytes.windows(4).position(|b| b == b"\r\n\r\n") {
            break index + 4;
        }
        if bytes.len() > 16 * 1024 {
            return Err((431, "headers too large".into()));
        }
        match stream.read(&mut chunk) {
            Ok(0) => return Err((400, "incomplete request".into())),
            Ok(n) => bytes.extend_from_slice(&chunk[..n]),
            Err(e)
                if matches!(
                    e.kind(),
                    std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
                ) =>
            {
                continue;
            }
            Err(e) => return Err((400, e.to_string())),
        }
    };
    let header = std::str::from_utf8(&bytes[..split]).map_err(|_| (400, "bad headers".into()))?;
    let mut lines = header.split("\r\n");
    let first = lines
        .next()
        .unwrap_or("")
        .split_whitespace()
        .collect::<Vec<_>>();
    if first.len() != 3 || !first[2].starts_with("HTTP/1.") {
        return Err((400, "bad request line".into()));
    }
    let method = first[0].to_owned();
    let path = first[1].to_owned();
    let mut authorization = String::new();
    let mut length = None;
    for line in lines.filter(|s| !s.is_empty()) {
        let Some((key, value)) = line.split_once(':') else {
            return Err((400, "bad header".into()));
        };
        if key.eq_ignore_ascii_case("authorization") {
            authorization = value.trim().into();
        }
        if key.eq_ignore_ascii_case("transfer-encoding") {
            return Err((400, "transfer encoding unsupported".into()));
        }
        if key.eq_ignore_ascii_case("content-length") {
            let n = value
                .trim()
                .parse::<usize>()
                .map_err(|_| (400, "bad content length".into()))?;
            if length.is_some_and(|prior| prior != n) {
                return Err((400, "conflicting content lengths".into()));
            }
            length = Some(n);
        }
    }
    if authorization != format!("Bearer {token}") {
        return Err((401, "unauthorised".into()));
    }
    let length = length.unwrap_or(0);
    if length > config.max_body_bytes {
        return Err((413, "body too large".into()));
    }
    let mut body = bytes[split..].to_vec();
    body.truncate(length);
    while body.len() < length {
        if stop.load(Ordering::Acquire) {
            return Err((503, "closing".into()));
        }
        if Instant::now() >= deadline {
            return Err((408, "request timed out".into()));
        }
        let read = (length - body.len()).min(chunk.len());
        match stream.read(&mut chunk[..read]) {
            Ok(0) => return Err((400, "incomplete body".into())),
            Ok(n) => body.extend_from_slice(&chunk[..n]),
            Err(e)
                if matches!(
                    e.kind(),
                    std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
                ) =>
            {
                continue;
            }
            Err(e) => return Err((400, e.to_string())),
        }
    }
    Ok(HttpRequest {
        method,
        path,
        authorization,
        body,
    })
}
fn respond(stream: &mut TcpStream, status: u16, value: &Value) {
    let Ok(body) = serde_json::to_vec(value) else {
        return;
    };
    let reason = match status {
        200 => "OK",
        400 => "Bad Request",
        401 => "Unauthorized",
        404 => "Not Found",
        405 => "Method Not Allowed",
        408 => "Request Timeout",
        413 => "Payload Too Large",
        431 => "Request Header Fields Too Large",
        503 => "Service Unavailable",
        _ => "Internal Server Error",
    };
    let header = format!(
        "HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    let _ = stream
        .write_all(header.as_bytes())
        .and_then(|_| stream.write_all(&body));
}
