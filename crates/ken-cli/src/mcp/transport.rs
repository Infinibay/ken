//! Pollable I/O owners isolate cancellation and backpressure from local tools.
use super::{
    ToolHandler,
    framing::{self, Frame},
    protocol::{self, Incoming, Protocol, Request, RequestKey},
};
use ken_query::execution::Cancellation;
use serde_json::Value;
use std::{
    collections::BTreeMap,
    io::{self, BufReader, Read, Write},
    os::fd::{AsRawFd, RawFd},
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
        mpsc::{self, SyncSender, TrySendError},
    },
    thread,
    time::{Duration, Instant},
};
const PENDING_REQUESTS: usize = 8;
const PENDING_OUTPUTS: usize = 16;
struct Shared {
    requests: Mutex<BTreeMap<RequestKey, Cancellation>>,
    abort: AtomicBool,
    error: Mutex<Option<io::Error>>,
}
impl Shared {
    fn new() -> Self {
        Self {
            requests: Mutex::new(BTreeMap::new()),
            abort: AtomicBool::new(false),
            error: Mutex::new(None),
        }
    }
    fn cancel_all(&self) {
        for cancellation in self
            .requests
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .values()
        {
            cancellation.cancel();
        }
    }
    fn fail(&self, error: io::Error) {
        let mut first = self.error.lock().unwrap_or_else(|e| e.into_inner());
        if first.is_none() {
            *first = Some(error);
        }
        drop(first);
        self.abort.store(true, Ordering::Release);
        self.cancel_all();
    }
}
struct Output {
    response: Value,
}
fn enqueue(sender: &SyncSender<Output>, shared: &Shared, response: Value) -> bool {
    match sender.try_send(Output { response }) {
        Ok(()) => true,
        Err(_) => {
            shared.fail(io::Error::other(
                "MCP output backlog exceeds bounded transport capacity",
            ));
            false
        }
    }
}
/// One nonblocking mode lease restores the descriptor before its owner closes.
struct Nonblocking {
    fd: RawFd,
    flags: i32,
}
impl Nonblocking {
    fn new(fd: RawFd) -> io::Result<Self> {
        let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
        if flags < 0 {
            return Err(io::Error::last_os_error());
        }
        if unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(Self { fd, flags })
    }
}
impl Drop for Nonblocking {
    fn drop(&mut self) {
        let _ = unsafe { libc::fcntl(self.fd, libc::F_SETFL, self.flags) };
    }
}
struct PollRead<R> {
    _mode: Nonblocking,
    input: R,
    shared: Arc<Shared>,
}
fn poll(fd: RawFd, event: i16, shared: &Shared) -> io::Result<()> {
    loop {
        if shared.abort.load(Ordering::Acquire) {
            return Err(io::Error::new(
                io::ErrorKind::Interrupted,
                "MCP transport closed",
            ));
        }
        let mut descriptor = libc::pollfd {
            fd,
            events: event,
            revents: 0,
        };
        let result = unsafe { libc::poll(&mut descriptor, 1, 50) };
        if result < 0 {
            let error = io::Error::last_os_error();
            if error.kind() == io::ErrorKind::Interrupted {
                continue;
            }
            return Err(error);
        }
        if result > 0 {
            if descriptor.revents & libc::POLLNVAL != 0 {
                return Err(io::Error::new(
                    io::ErrorKind::BrokenPipe,
                    "MCP descriptor closed",
                ));
            }
            return Ok(());
        }
    }
}
impl<R: Read + AsRawFd> Read for PollRead<R> {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        loop {
            poll(self.input.as_raw_fd(), libc::POLLIN, &self.shared)?;
            match self.input.read(bytes) {
                Err(error)
                    if matches!(
                        error.kind(),
                        io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                    ) =>
                {
                    continue;
                }
                result => return result,
            }
        }
    }
}
struct PollWrite<W> {
    _mode: Nonblocking,
    output: W,
    shared: Arc<Shared>,
    last_progress: Instant,
}
impl<W: Write + AsRawFd> Write for PollWrite<W> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        loop {
            if self.shared.abort.load(Ordering::Acquire) {
                return Err(io::Error::new(
                    io::ErrorKind::BrokenPipe,
                    "MCP transport closed",
                ));
            }
            if self.last_progress.elapsed() > Duration::from_secs(5) {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "MCP output made no progress for5s",
                ));
            }
            let mut descriptor = libc::pollfd {
                fd: self.output.as_raw_fd(),
                events: libc::POLLOUT,
                revents: 0,
            };
            let ready = unsafe { libc::poll(&mut descriptor, 1, 50) };
            if ready < 0 {
                let error = io::Error::last_os_error();
                if error.kind() == io::ErrorKind::Interrupted {
                    continue;
                }
                return Err(error);
            }
            if ready == 0 {
                continue;
            }
            match self.output.write(bytes) {
                Ok(n) => {
                    if n > 0 {
                        self.last_progress = Instant::now();
                    }
                    return Ok(n);
                }
                Err(error)
                    if matches!(
                        error.kind(),
                        io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                    ) =>
                {
                    continue;
                }
                Err(error) => return Err(error),
            }
        }
    }
    fn flush(&mut self) -> io::Result<()> {
        self.output.flush()
    }
}
fn read_loop<R: Read + AsRawFd>(
    input: R,
    requests: SyncSender<Request>,
    outputs: SyncSender<Output>,
    shared: Arc<Shared>,
) -> io::Result<()> {
    let mode = Nonblocking::new(input.as_raw_fd())?;
    let mut reader = BufReader::new(PollRead {
        _mode: mode,
        input,
        shared: shared.clone(),
    });
    while !shared.abort.load(Ordering::Acquire) {
        let frame = match framing::read(&mut reader) {
            Ok(Some(frame)) => frame,
            Ok(None) => {
                shared.cancel_all();
                return Ok(());
            }
            Err(error)
                if shared.abort.load(Ordering::Acquire)
                    && error.kind() == io::ErrorKind::Interrupted =>
            {
                return Ok(());
            }
            Err(error) => return Err(error),
        };
        let incoming = match frame {
            Frame::Bytes(bytes) => protocol::decode(&bytes),
            Frame::Oversized => Incoming::Error(protocol::error(
                Value::Null,
                -32700,
                "MCP frame exceeds8MiB",
            )),
        };
        match incoming {
            Incoming::Ignored => (),
            Incoming::Cancel(key) => {
                if let Some(cancellation) = shared
                    .requests
                    .lock()
                    .unwrap_or_else(|e| e.into_inner())
                    .get(&key)
                {
                    cancellation.cancel();
                }
            }
            Incoming::Error(response) => {
                if !enqueue(&outputs, &shared, response) {
                    return Ok(());
                }
            }
            Incoming::Request(request) => {
                let mut registry = shared.requests.lock().unwrap_or_else(|e| e.into_inner());
                if registry.contains_key(&request.key) {
                    drop(registry);
                    if !enqueue(
                        &outputs,
                        &shared,
                        protocol::error(request.id, -32600, "request ID is already in flight"),
                    ) {
                        return Ok(());
                    }
                    continue;
                }
                registry.insert(request.key.clone(), request.cancellation.clone());
                drop(registry);
                match requests.try_send(request) {
                    Ok(()) => (),
                    Err(TrySendError::Full(request)) => {
                        shared
                            .requests
                            .lock()
                            .unwrap_or_else(|e| e.into_inner())
                            .remove(&request.key);
                        if !enqueue(
                            &outputs,
                            &shared,
                            protocol::error(
                                request.id,
                                -32000,
                                "MCP request backlog exceeds bounded transport capacity",
                            ),
                        ) {
                            return Ok(());
                        }
                    }
                    Err(TrySendError::Disconnected(_)) => return Ok(()),
                }
            }
        }
    }
    Ok(())
}
fn write_loop<W: Write + AsRawFd>(
    output: W,
    outputs: mpsc::Receiver<Output>,
    shared: Arc<Shared>,
) -> io::Result<()> {
    let mode = Nonblocking::new(output.as_raw_fd())?;
    let mut writer = PollWrite {
        _mode: mode,
        output,
        shared: shared.clone(),
        last_progress: Instant::now(),
    };
    while !shared.abort.load(Ordering::Acquire) {
        match outputs.recv_timeout(Duration::from_millis(50)) {
            Ok(Output { response }) => {
                writer.last_progress = Instant::now();
                serde_json::to_writer(&mut writer, &response)?;
                writer.write_all(b"\n")?;
                writer.flush()?;
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => return Ok(()),
            Err(mpsc::RecvTimeoutError::Timeout) => (),
        }
    }
    Ok(())
}
/// The service remains on this thread. Only framed I/O and cancellation flags
/// cross threads; every I/O owner is joined before this function returns.
pub fn serve_transport<R, W>(input: R, output: W, handler: &mut dyn ToolHandler) -> io::Result<()>
where
    R: Read + AsRawFd + Send + 'static,
    W: Write + AsRawFd + Send + 'static,
{
    let shared = Arc::new(Shared::new());
    let (requests_tx, requests_rx) = mpsc::sync_channel(PENDING_REQUESTS);
    let (outputs_tx, outputs_rx) = mpsc::sync_channel(PENDING_OUTPUTS);
    let writer_shared = shared.clone();
    let writer = thread::Builder::new()
        .name("ken-mcp-writer".into())
        .spawn(move || {
            if let Err(error) = write_loop(output, outputs_rx, writer_shared.clone()) {
                writer_shared.fail(error);
            }
        })?;
    let reader_shared = shared.clone();
    let reader_output = outputs_tx.clone();
    let reader = match thread::Builder::new()
        .name("ken-mcp-reader".into())
        .spawn(move || {
            if let Err(error) = read_loop(input, requests_tx, reader_output, reader_shared.clone())
            {
                reader_shared.fail(error);
            }
        }) {
        Ok(reader) => reader,
        Err(error) => {
            shared.fail(error);
            drop(outputs_tx);
            let _ = writer.join();
            return Err(shared
                .error
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .take()
                .unwrap_or_else(|| io::Error::other("MCP reader startup failed")));
        }
    };
    let mut protocol = Protocol::default();
    while !shared.abort.load(Ordering::Acquire) {
        let request = match requests_rx.recv_timeout(Duration::from_millis(50)) {
            Ok(request) => request,
            Err(mpsc::RecvTimeoutError::Disconnected) => break,
            Err(mpsc::RecvTimeoutError::Timeout) => continue,
        };
        if request.cancellation.is_cancelled() {
            shared
                .requests
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .remove(&request.key);
            continue;
        }
        let response = protocol.handle(&request, handler);
        // Atomic settlement: cancellation before this commit suppresses success AND
        // error. EOF only cancels still-registered work; committed replies drain.
        let mut registry = shared.requests.lock().unwrap_or_else(|e| e.into_inner());
        let cancelled = request.cancellation.is_cancelled();
        registry.remove(&request.key);
        if !cancelled && outputs_tx.try_send(Output { response }).is_err() {
            drop(registry);
            shared.fail(io::Error::other(
                "MCP output backlog exceeds bounded transport capacity",
            ));
            break;
        }
        drop(registry);
    }
    if shared.abort.load(Ordering::Acquire) {
        shared.cancel_all();
    }
    if reader.join().is_err() {
        shared.fail(io::Error::other("MCP reader panicked"));
    }
    drop(outputs_tx);
    if writer.join().is_err() {
        shared.fail(io::Error::other("MCP writer panicked"));
    }
    let error = shared
        .error
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .take();
    error.map_or(Ok(()), Err)
}
