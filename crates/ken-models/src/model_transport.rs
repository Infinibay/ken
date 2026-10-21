//! Anonymous pinned public HTTPS; the cache owns length/hash verification.
use crate::{ArtifactRequest, ArtifactTransport, ModelError};
use std::{io::Read, time::Duration};
use ureq::{
    Agent,
    unversioned::{
        resolver::DefaultResolver,
        transport::{
            Buffers, ConnectionDetails, Connector, DefaultConnector, NextTimeout, Transport,
        },
    },
};

pub struct PublicModelTransport {
    agent: Agent,
    base: String,
}

// ureq's recv_body timeout is TOTAL, not inactivity. Bound every underlying
// wait instead, retaining any shorter remaining global/connect deadline.
#[derive(Debug)]
struct IdleConnector(Duration);
#[derive(Debug)]
struct IdleTransport<T> {
    inner: T,
    maximum_wait: Duration,
}

impl<T: Transport> Connector<T> for IdleConnector {
    type Out = IdleTransport<T>;
    fn connect(
        &self,
        _: &ConnectionDetails,
        chained: Option<T>,
    ) -> Result<Option<Self::Out>, ureq::Error> {
        Ok(chained.map(|inner| IdleTransport {
            inner,
            maximum_wait: self.0,
        }))
    }
}
impl<T: Transport> Transport for IdleTransport<T> {
    fn buffers(&mut self) -> &mut dyn Buffers {
        self.inner.buffers()
    }
    fn transmit_output(&mut self, amount: usize, timeout: NextTimeout) -> Result<(), ureq::Error> {
        self.inner.transmit_output(amount, timeout)
    }
    fn await_input(&mut self, mut timeout: NextTimeout) -> Result<bool, ureq::Error> {
        if timeout.after > self.maximum_wait.into() {
            timeout.after = self.maximum_wait.into();
            timeout.reason = ureq::Timeout::RecvBody;
        }
        self.inner.await_input(timeout)
    }
    fn is_open(&mut self) -> bool {
        self.inner.is_open()
    }
    fn is_tls(&self) -> bool {
        self.inner.is_tls()
    }
}

impl PublicModelTransport {
    pub fn new() -> Result<Self, ModelError> {
        Ok(Self::build(
            "https://huggingface.co".into(),
            true,
            Duration::from_secs(60),
            Duration::from_secs(3600),
        ))
    }

    fn build(base: String, https_only: bool, inactivity: Duration, total: Duration) -> Self {
        let config = Agent::config_builder()
            .https_only(https_only)
            .proxy(None)
            .http_status_as_error(true)
            .max_redirects(10)
            .max_redirects_will_error(true)
            .redirect_auth_headers(ureq::config::RedirectAuthHeaders::Never)
            .timeout_global(Some(total))
            .timeout_connect(Some(Duration::from_secs(15)))
            .timeout_resolve(Some(Duration::from_secs(15)))
            .timeout_send_request(Some(inactivity))
            .timeout_recv_body(None)
            .build();
        let connector = DefaultConnector::default().chain(IdleConnector(inactivity));
        Self {
            agent: Agent::with_parts(config, connector, DefaultResolver::default()),
            base,
        }
    }

    #[cfg(test)]
    fn for_test(base: &str, inactivity: Duration, total: Duration) -> Self {
        Self::build(base.to_owned(), false, inactivity, total)
    }

    fn url(&self, request: &ArtifactRequest) -> Result<String, ModelError> {
        let parts: Vec<_> = request.model_id.split('/').collect();
        if parts.len() != 2
            || parts.iter().any(|part| {
                part.is_empty()
                    || matches!(*part, "." | "..")
                    || !part
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b"_.-".contains(&b))
            })
            || !crate::profile::hex_revision(&request.revision, &[40])
            || !crate::assets::valid_artifact_name(&request.name)
        {
            return Err(ModelError::Registration(
                "immutable public model artifact request required".into(),
            ));
        }
        Ok(format!(
            "{}/{}/resolve/{}/{}",
            self.base, request.model_id, request.revision, request.name
        ))
    }
}

impl ArtifactTransport for PublicModelTransport {
    fn open(&self, request: &ArtifactRequest) -> Result<Box<dyn Read + Send>, ModelError> {
        let response = self
            .agent
            .get(self.url(request)?)
            .header("accept-encoding", "identity")
            .call()
            .map_err(|e| ModelError::Runtime(format!("public model HTTP: {e}")))?;
        if response.status().as_u16() != 200 {
            return Err(ModelError::Runtime(
                "complete public artifact response required".into(),
            ));
        }
        if response
            .headers()
            .get("content-encoding")
            .is_some_and(|value| value != "identity")
        {
            return Err(ModelError::Runtime(
                "encoded public artifact response is unsupported".into(),
            ));
        }
        Ok(Box::new(response.into_body().into_reader()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{AcquisitionPolicy, ArtifactCache, ModelAssets};
    use std::{
        io::{Read, Write},
        net::{TcpListener, TcpStream},
        sync::{
            Arc, Mutex,
            atomic::{AtomicBool, Ordering},
        },
        thread,
        time::{Duration, Instant},
    };

    struct Server {
        url: String,
        requests: Arc<Mutex<Vec<String>>>,
        stop: Arc<AtomicBool>,
        worker: Option<thread::JoinHandle<()>>,
    }
    impl Server {
        fn new(mut respond: impl FnMut(&mut TcpStream) + Send + 'static) -> Self {
            let listener = TcpListener::bind("127.0.0.1:0").unwrap();
            listener.set_nonblocking(true).unwrap();
            let url = format!("http://{}", listener.local_addr().unwrap());
            let requests = Arc::new(Mutex::new(Vec::new()));
            let seen = requests.clone();
            let stop = Arc::new(AtomicBool::new(false));
            let ended = stop.clone();
            let worker = thread::spawn(move || {
                while !ended.load(Ordering::SeqCst) {
                    let (mut stream, _) = match listener.accept() {
                        Ok(value) => value,
                        Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                            thread::sleep(Duration::from_millis(1));
                            continue;
                        }
                        Err(error) => panic!("test accept: {error}"),
                    };
                    // Accepted sockets inherit nonblocking mode on macOS.
                    stream.set_nonblocking(false).unwrap();
                    stream
                        .set_read_timeout(Some(Duration::from_secs(1)))
                        .unwrap();
                    stream
                        .set_write_timeout(Some(Duration::from_secs(1)))
                        .unwrap();
                    let mut request = Vec::new();
                    let mut byte = [0];
                    while request.len() < 8192 && !request.ends_with(b"\r\n\r\n") {
                        match stream.read(&mut byte) {
                            Ok(1) => request.push(byte[0]),
                            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => {
                                continue;
                            }
                            _ => break,
                        }
                    }
                    seen.lock()
                        .unwrap()
                        .push(String::from_utf8(request).unwrap());
                    respond(&mut stream);
                }
            });
            Self {
                url,
                requests,
                stop,
                worker: Some(worker),
            }
        }
        fn fixed(raw: &'static [u8]) -> Self {
            Self::new(move |stream| {
                let _ = stream.write_all(raw);
            })
        }
        fn transport(&self) -> PublicModelTransport {
            PublicModelTransport::for_test(
                &self.url,
                Duration::from_millis(120),
                Duration::from_secs(2),
            )
        }
    }
    impl Drop for Server {
        fn drop(&mut self) {
            self.stop.store(true, Ordering::SeqCst);
            self.worker.take().unwrap().join().unwrap();
        }
    }
    fn request() -> crate::ArtifactRequest {
        crate::ArtifactRequest {
            model_id: "public/model".into(),
            revision: "a".repeat(40),
            name: "nested/config.json".into(),
        }
    }
    fn declaration(size: usize) -> ModelAssets {
        use sha2::{Digest, Sha256};
        let bytes = &b"abcde"[..size];
        ModelAssets::from_json(
            &serde_json::json!({"model_id":"public/model","revision":"a".repeat(40),"artifacts":{
                "nested/config.json":{"bytes":size,"sha256":format!("{:x}",Sha256::digest(bytes))}
            }})
            .to_string(),
        )
        .unwrap()
    }

    #[test]
    fn real_chunked_response_streams_into_a_verified_cache_with_exact_anonymous_request() {
        let server = Server::fixed(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n3\r\nabc\r\n0\r\n\r\n");
        let temp = tempfile::tempdir().unwrap();
        let cache = ArtifactCache::new(temp.path()).unwrap();
        let path = cache
            .resolve(
                &declaration(3),
                AcquisitionPolicy::Public,
                &server.transport(),
            )
            .unwrap();
        assert_eq!(
            std::fs::read(path.join("nested/config.json")).unwrap(),
            b"abc"
        );
        let requests = server.requests.lock().unwrap();
        assert_eq!(requests.len(), 1);
        assert!(
            requests[0].starts_with(&format!(
                "GET /public/model/resolve/{}/nested/config.json HTTP/1.1\r\n",
                "a".repeat(40)
            )),
            "{}",
            requests[0]
        );
        let raw = requests[0].to_ascii_lowercase();
        assert!(!raw.contains("authorization:") && !raw.contains("cookie:"));
        assert!(raw.contains("accept-encoding: identity\r\n"));
    }

    #[test]
    fn status_length_chunking_encoding_and_excess_bytes_cannot_publish_partial_data() {
        let cases: &[&[u8]] = &[
            b"HTTP/1.1 404 Not Found\r\nContent-Length:0\r\nConnection:close\r\n\r\n",
            b"HTTP/1.1 500 Error\r\nContent-Length:0\r\nConnection:close\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nContent-Length:5\r\nConnection:close\r\n\r\nabc",
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding:chunked\r\nConnection:close\r\n\r\n5\r\nabc",
            b"HTTP/1.1 200 OK\r\nContent-Length:4\r\nConnection:close\r\n\r\nabcd",
            b"HTTP/1.1 200 OK\r\nContent-Length:3\r\nContent-Encoding:gzip\r\nConnection:close\r\n\r\nabc",
        ];
        for raw in cases {
            let raw = raw.to_vec();
            let server = Server::new(move |stream| {
                let _ = stream.write_all(&raw);
            });
            let temp = tempfile::tempdir().unwrap();
            let cache = ArtifactCache::new(temp.path()).unwrap();
            assert!(
                cache
                    .resolve(
                        &declaration(3),
                        AcquisitionPolicy::Public,
                        &server.transport()
                    )
                    .is_err()
            );
            let model = temp
                .path()
                .join("models")
                .join(declaration(3).fingerprint());
            assert!(std::fs::read_dir(model).unwrap().next().is_none());
        }
    }

    #[test]
    fn real_redirect_loop_stops_after_ten_and_never_publishes() {
        let server = Server::fixed(
            b"HTTP/1.1 302 Found\r\nLocation:/loop\r\nContent-Length:0\r\nConnection:close\r\n\r\n",
        );
        assert!(server.transport().open(&request()).is_err());
        assert_eq!(server.requests.lock().unwrap().len(), 11);
    }

    #[test]
    fn production_agent_refuses_http_before_connecting() {
        let server = Server::fixed(b"HTTP/1.1 200 OK\r\nContent-Length:0\r\n\r\n");
        let transport = PublicModelTransport::new().unwrap();
        assert!(transport.agent.get(&server.url).call().is_err());
        assert!(server.requests.lock().unwrap().is_empty());
    }

    #[test]
    fn a_stalled_body_times_out_but_active_reads_can_outlive_one_inactivity_interval() {
        let stalled = Server::new(|stream| {
            let _ = stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length:3\r\nConnection:close\r\n\r\n");
            thread::sleep(Duration::from_millis(300));
            let _ = stream.write_all(b"abc");
        });
        let start = Instant::now();
        let mut reader = stalled.transport().open(&request()).unwrap();
        assert!(reader.read_to_end(&mut Vec::new()).is_err());
        assert!(start.elapsed() < Duration::from_secs(1));
        let active = Server::new(|stream| {
            let _ = stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length:3\r\nConnection:close\r\n\r\n");
            for byte in b"abc" {
                thread::sleep(Duration::from_millis(70));
                if stream.write_all(&[*byte]).is_err() {
                    break;
                }
            }
        });
        let mut result = Vec::new();
        active
            .transport()
            .open(&request())
            .unwrap()
            .read_to_end(&mut result)
            .unwrap();
        assert_eq!(result, b"abc");
    }

    #[test]
    fn total_deadline_still_bounds_a_continuously_progressing_body() {
        let server = Server::new(|stream| {
            let _ = stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length:5\r\nConnection:close\r\n\r\n");
            for byte in b"abcde" {
                thread::sleep(Duration::from_millis(70));
                if stream.write_all(&[*byte]).is_err() {
                    break;
                }
            }
        });
        let transport = PublicModelTransport::for_test(
            &server.url,
            Duration::from_millis(150),
            Duration::from_millis(220),
        );
        let mut reader = transport.open(&request()).unwrap();
        assert!(reader.read_to_end(&mut Vec::new()).is_err());
    }
}
