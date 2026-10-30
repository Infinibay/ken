//! Authenticated local client. Accepted response timeouts never trigger a spawn.
use crate::{Error, Result, runtime::FileLock};
use serde_json::Value;
use std::{
    collections::BTreeMap,
    ffi::OsString,
    fs::{self, OpenOptions},
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    os::unix::process::CommandExt,
    path::{Path, PathBuf},
    process::{Command, Stdio},
    thread,
    time::{Duration, Instant},
};
#[derive(Clone, Debug)]
pub struct Program {
    pub executable: PathBuf,
    pub arguments: Vec<OsString>,
    pub environment: BTreeMap<OsString, OsString>,
}
impl Program {
    pub fn new(executable: impl Into<PathBuf>) -> Self {
        Self {
            executable: executable.into(),
            arguments: Vec::new(),
            environment: BTreeMap::new(),
        }
    }
}
#[derive(Clone, Debug)]
pub struct ClientOptions {
    pub health_timeout: Duration,
    pub post_timeout: Duration,
    pub rank_timeout: Duration,
    pub spawn_timeout: Duration,
    pub poll_interval: Duration,
    pub max_response_bytes: usize,
}
impl Default for ClientOptions {
    fn default() -> Self {
        Self {
            health_timeout: Duration::from_secs(1),
            post_timeout: Duration::from_secs(3),
            rank_timeout: Duration::from_secs(60),
            spawn_timeout: Duration::from_secs(5),
            poll_interval: Duration::from_millis(50),
            max_response_bytes: 8 * 1024 * 1024,
        }
    }
}
pub struct Client {
    root: PathBuf,
    program: Program,
    options: ClientOptions,
}
impl Client {
    pub fn new(root: &Path, program: Program, options: ClientOptions) -> Self {
        Self {
            root: root.into(),
            program,
            options,
        }
    }
    pub fn health(&self) -> Option<Value> {
        let port = self.read_port()?;
        self.request("GET", port, "/health", None, self.options.health_timeout)
            .ok()
    }
    /// Contact only an already advertised service; lifecycle cleanup must not spawn.
    pub fn post_existing(&self, path: &str, payload: &Value) -> Result<Option<Value>> {
        let Some(port) = self.read_port() else {
            return Ok(None);
        };
        match self.request("POST", port, path, Some(payload), self.timeout(path)) {
            Ok(value) => Ok(Some(value)),
            Err(Error::AcceptedTimeout | Error::Io(_)) => Ok(None),
            Err(error) => Err(error),
        }
    }
    /// Wait for the runtime owner to finish storage and workers before removal.
    pub fn stop_existing(&self) -> Result<()> {
        use std::os::{fd::AsRawFd, unix::fs::OpenOptionsExt};
        let _ = self.post_existing("/shutdown", &serde_json::json!({}))?;
        let deadline = Instant::now() + self.options.spawn_timeout;
        loop {
            let lock = OpenOptions::new()
                .read(true)
                .write(true)
                .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
                .open(self.root.join(".ken/daemon.lock"));
            let idle = match lock {
                Ok(file) => {
                    if !file.metadata()?.is_file() {
                        return Err(Error::Invalid(
                            "daemon ownership lock is not a regular file".into(),
                        ));
                    }
                    if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0
                    {
                        true
                    } else {
                        let error = std::io::Error::last_os_error();
                        if error.raw_os_error() == Some(libc::EWOULDBLOCK) {
                            false
                        } else {
                            return Err(error.into());
                        }
                    }
                }
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => true,
                Err(error) => return Err(error.into()),
            };
            if idle {
                if self.health().is_none() {
                    return Ok(());
                }
                return Err(Error::Invalid(
                    "daemon still advertises a live service without an ownership lock".into(),
                ));
            }
            if Instant::now() >= deadline {
                return Err(Error::Invalid(
                    "daemon did not release ownership after shutdown".into(),
                ));
            }
            thread::sleep(
                self.options
                    .poll_interval
                    .min(deadline.saturating_duration_since(Instant::now())),
            );
        }
    }
    fn timeout(&self, path: &str) -> Duration {
        if ["/prompts", "/rank", "/explain"].contains(&path) {
            self.options.rank_timeout
        } else {
            self.options.post_timeout
        }
    }
    pub fn post(&self, path: &str, payload: &Value) -> Result<Option<Value>> {
        let timeout = self.timeout(path);
        if let Some(port) = self.read_port() {
            match self.request("POST", port, path, Some(payload), timeout) {
                Ok(value) => return Ok(Some(value)),
                Err(Error::AcceptedTimeout) => return Ok(None),
                Err(Error::Io(_)) => self.clear_if_port(port),
                Err(error) => return Err(error),
            }
        }
        let port = self.spawn_and_wait()?;
        match self.request("POST", port, path, Some(payload), timeout) {
            Ok(value) => Ok(Some(value)),
            Err(Error::AcceptedTimeout) => Ok(None),
            Err(error) => Err(error),
        }
    }
    fn read_port(&self) -> Option<u16> {
        fs::read_to_string(self.root.join(".ken/daemon.port"))
            .ok()?
            .trim()
            .parse::<u16>()
            .ok()
            .filter(|n| *n > 0)
    }
    fn clear_if_port(&self, port: u16) {
        if self.read_port() == Some(port) {
            let _ = fs::remove_file(self.root.join(".ken/daemon.port"));
        }
    }
    fn token(&self) -> Result<String> {
        let meta: Value = serde_json::from_slice(&fs::read(self.root.join(".ken/meta.json"))?)?;
        meta["auth_token"]
            .as_str()
            .map(str::to_owned)
            .ok_or_else(|| Error::Invalid("missing project auth_token".into()))
    }
    fn spawn_and_wait(&self) -> Result<u16> {
        let _lock = FileLock::acquire(&self.root.join(".ken/daemon.spawn.lock"), false)?;
        if self.health().is_some() {
            return self.read_port().ok_or(Error::Closed);
        }
        let log = OpenOptions::new()
            .append(true)
            .create(true)
            .open(self.root.join(".ken/daemon.log"))?;
        let mut command = Command::new(&self.program.executable);
        command
            .args(&self.program.arguments)
            .envs(&self.program.environment)
            .env("KEN_PROJECT_ROOT", &self.root)
            .current_dir(&self.root)
            .stdin(Stdio::null())
            .stdout(Stdio::from(log.try_clone()?))
            .stderr(Stdio::from(log));
        unsafe {
            command.pre_exec(|| {
                if libc::setsid() == -1 {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(())
            });
        }
        let mut child = command.spawn()?;
        thread::Builder::new()
            .name("ken-daemon-reaper".into())
            .spawn(move || {
                let _ = child.wait();
            })?;
        let deadline = Instant::now() + self.options.spawn_timeout;
        while Instant::now() < deadline {
            if let Some(port) = self.read_port()
                && self
                    .request("GET", port, "/health", None, self.options.health_timeout)
                    .is_ok()
            {
                return Ok(port);
            }
            thread::sleep(self.options.poll_interval);
        }
        Err(Error::Invalid(format!(
            "daemon did not come up within {:.1}s",
            self.options.spawn_timeout.as_secs_f64()
        )))
    }
    fn request(
        &self,
        method: &str,
        port: u16,
        path: &str,
        payload: Option<&Value>,
        timeout: Duration,
    ) -> Result<Value> {
        if !path.starts_with('/') || path.bytes().any(|b| b == b'\r' || b == b'\n' || b == b' ') {
            return Err(Error::Invalid("invalid local request path".into()));
        }
        let token = self.token()?;
        if token.contains(['\r', '\n']) {
            return Err(Error::Invalid("invalid auth token".into()));
        }
        let address = SocketAddr::from(([127, 0, 0, 1], port));
        let mut stream = TcpStream::connect_timeout(&address, timeout)?;
        stream.set_read_timeout(Some(timeout))?;
        stream.set_write_timeout(Some(timeout))?;
        let started = Instant::now();
        let body = payload
            .map(serde_json::to_vec)
            .transpose()?
            .unwrap_or_default();
        let header = format!(
            "{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nAuthorization: Bearer {token}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            body.len()
        );
        let accepted = |e: std::io::Error| {
            if matches!(
                e.kind(),
                std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock
            ) {
                Error::AcceptedTimeout
            } else {
                Error::Invalid(format!("accepted daemon connection failed: {e}"))
            }
        };
        stream
            .write_all(header.as_bytes())
            .and_then(|_| stream.write_all(&body))
            .map_err(accepted)?;
        let mut response = Vec::new();
        let mut chunk = [0u8; 4096];
        loop {
            if started.elapsed() >= timeout {
                return Err(Error::AcceptedTimeout);
            }
            stream.set_read_timeout(Some(
                timeout
                    .saturating_sub(started.elapsed())
                    .max(Duration::from_millis(1)),
            ))?;
            let n = stream.read(&mut chunk).map_err(accepted)?;
            if n == 0 {
                break;
            }
            if response.len() + n > self.options.max_response_bytes + 16 * 1024 {
                return Err(Error::Invalid("daemon response exceeds bound".into()));
            }
            response.extend_from_slice(&chunk[..n]);
        }
        let split = response
            .windows(4)
            .position(|b| b == b"\r\n\r\n")
            .ok_or_else(|| Error::Invalid("invalid daemon HTTP response".into()))?;
        let header = std::str::from_utf8(&response[..split]).map_err(crate::invalid)?;
        let status = header
            .lines()
            .next()
            .and_then(|line| line.split_whitespace().nth(1))
            .and_then(|s| s.parse::<u16>().ok())
            .ok_or_else(|| Error::Invalid("invalid daemon HTTP status".into()))?;
        if !(200..300).contains(&status) {
            return Err(Error::Http(status));
        }
        let bytes = &response[split + 4..];
        if bytes.len() > self.options.max_response_bytes {
            return Err(Error::Invalid("daemon response exceeds bound".into()));
        }
        if bytes.is_empty() {
            Ok(serde_json::json!({}))
        } else {
            Ok(serde_json::from_slice(bytes)?)
        }
    }
}
