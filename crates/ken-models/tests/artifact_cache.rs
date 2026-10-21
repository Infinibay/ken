//! Cache ownership and publication through the same public consumer as the factory.
use ken_models::{
    AcquisitionPolicy, ArtifactCache, ArtifactRequest, ArtifactTransport, ModelAssets, ModelError,
};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs,
    io::{self, Cursor, Read},
    path::Path,
    sync::{
        Arc, Barrier,
        atomic::{AtomicUsize, Ordering},
    },
};

const REVISION: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

fn assets(model: &str, files: &[(&str, &[u8])]) -> ModelAssets {
    let records: BTreeMap<_, _> = files
        .iter()
        .map(|(name, bytes)| {
            (
                *name,
                json!({
                    "bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(bytes))
                }),
            )
        })
        .collect();
    ModelAssets::from_json(
        &json!({"model_id":model,"revision":REVISION,"artifacts":records}).to_string(),
    )
    .unwrap()
}

struct Memory {
    files: BTreeMap<String, Vec<u8>>,
    calls: AtomicUsize,
}
impl Memory {
    fn new(files: &[(&str, &[u8])]) -> Self {
        Self {
            files: files
                .iter()
                .map(|(name, raw)| (name.to_string(), raw.to_vec()))
                .collect(),
            calls: AtomicUsize::new(0),
        }
    }
}
impl ArtifactTransport for Memory {
    fn open(&self, request: &ArtifactRequest) -> Result<Box<dyn Read + Send>, ModelError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        assert_eq!(request.revision, REVISION);
        Ok(Box::new(Cursor::new(self.files[&request.name].clone())))
    }
}

fn ready(root: &Path, declaration: &ModelAssets) -> std::path::PathBuf {
    root.join("models")
        .join(declaration.fingerprint())
        .join(REVISION)
}

fn no_stages(root: &Path) {
    for entry in fs::read_dir(root.join("models")).unwrap() {
        let directory = entry.unwrap().path();
        if directory.is_dir() {
            assert!(fs::read_dir(directory).unwrap().all(|entry| {
                !entry
                    .unwrap()
                    .file_name()
                    .to_string_lossy()
                    .starts_with("ken-artifacts-")
            }));
        }
    }
}

#[test]
fn publication_is_complete_nested_zero_length_verified_and_reused_without_transport() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("cache");
    let cache = ArtifactCache::new(&root).unwrap();
    let files: &[(&str, &[u8])] = &[
        ("config.json", b"{}"),
        ("nested/weights", b"weights"),
        ("empty", b""),
    ];
    let declaration = assets("public/model", files);
    let transport = Memory::new(files);
    let path = cache
        .resolve(&declaration, AcquisitionPolicy::Public, &transport)
        .unwrap();
    assert_eq!(path, ready(&root, &declaration));
    declaration.verify(&path).unwrap();
    assert_eq!(transport.calls.load(Ordering::SeqCst), 3);
    assert_eq!(
        cache
            .resolve(&declaration, AcquisitionPolicy::Offline, &transport)
            .unwrap(),
        path
    );
    assert_eq!(
        cache
            .resolve(&declaration, AcquisitionPolicy::Public, &transport)
            .unwrap(),
        path
    );
    assert_eq!(transport.calls.load(Ordering::SeqCst), 3);
    no_stages(&root);
}

#[test]
fn missing_offline_and_corrupt_existing_data_never_call_transport_or_delete_the_snapshot() {
    let temp = tempfile::tempdir().unwrap();
    let cache = ArtifactCache::new(temp.path()).unwrap();
    let declaration = assets("public/model", &[("data", b"abc")]);
    let transport = Memory::new(&[("data", b"abc")]);
    assert!(
        cache
            .resolve(&declaration, AcquisitionPolicy::Offline, &transport)
            .is_err()
    );
    assert_eq!(transport.calls.load(Ordering::SeqCst), 0);
    let path = cache
        .resolve(&declaration, AcquisitionPolicy::Public, &transport)
        .unwrap();
    fs::write(path.join("data"), b"bad").unwrap();
    assert!(
        cache
            .resolve(&declaration, AcquisitionPolicy::Public, &transport)
            .is_err()
    );
    assert_eq!(transport.calls.load(Ordering::SeqCst), 1);
    assert_eq!(fs::read(path.join("data")).unwrap(), b"bad");
    no_stages(temp.path());
}

#[test]
fn truncated_wrong_digest_overlong_or_failed_writes_never_publish_and_clean_their_stage() {
    for actual in [b"ab".as_slice(), b"bad", b"abcd"] {
        let temp = tempfile::tempdir().unwrap();
        let cache = ArtifactCache::new(temp.path()).unwrap();
        let declaration = assets("public/model", &[("data", b"abc")]);
        assert!(
            cache
                .resolve(
                    &declaration,
                    AcquisitionPolicy::Public,
                    &Memory::new(&[("data", actual)])
                )
                .is_err()
        );
        assert!(!ready(temp.path(), &declaration).exists());
        no_stages(temp.path());
    }
    let temp = tempfile::tempdir().unwrap();
    let cache = ArtifactCache::new(temp.path()).unwrap();
    let declaration = assets("public/model", &[("a", b"a"), ("a/b", b"b")]);
    assert!(
        cache
            .resolve(
                &declaration,
                AcquisitionPolicy::Public,
                &Memory::new(&[("a", b"a"), ("a/b", b"b")])
            )
            .is_err()
    );
    assert!(!ready(temp.path(), &declaration).exists());
    no_stages(temp.path());
}

struct MeasuredRead {
    consumed: Arc<AtomicUsize>,
    left: usize,
    interrupt: bool,
    fail: bool,
}
impl Read for MeasuredRead {
    fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
        if self.interrupt {
            self.interrupt = false;
            return Err(io::ErrorKind::Interrupted.into());
        }
        if self.fail {
            return Err(io::ErrorKind::UnexpectedEof.into());
        }
        let n = buffer.len().min(self.left);
        buffer[..n].fill(b'a');
        self.left -= n;
        self.consumed.fetch_add(n, Ordering::SeqCst);
        Ok(n)
    }
}
struct Measured {
    consumed: Arc<AtomicUsize>,
    bytes: usize,
    interrupt: bool,
    fail: bool,
}
impl ArtifactTransport for Measured {
    fn open(&self, _: &ArtifactRequest) -> Result<Box<dyn Read + Send>, ModelError> {
        Ok(Box::new(MeasuredRead {
            consumed: self.consumed.clone(),
            left: self.bytes,
            interrupt: self.interrupt,
            fail: self.fail,
        }))
    }
}

#[test]
fn streaming_stops_at_first_excess_byte_and_retries_only_real_interrupted_reads() {
    for (bytes, interrupt, fail, success) in [
        (1_000_000, false, false, false),
        (3, true, false, true),
        (3, false, true, false),
    ] {
        let temp = tempfile::tempdir().unwrap();
        let cache = ArtifactCache::new(temp.path()).unwrap();
        let declaration = assets("public/model", &[("data", b"aaa")]);
        let consumed = Arc::new(AtomicUsize::new(0));
        let result = cache.resolve(
            &declaration,
            AcquisitionPolicy::Public,
            &Measured {
                consumed: consumed.clone(),
                bytes,
                interrupt,
                fail,
            },
        );
        assert_eq!(result.is_ok(), success);
        assert!(consumed.load(Ordering::SeqCst) <= 4);
        assert_eq!(ready(temp.path(), &declaration).exists(), success);
        no_stages(temp.path());
    }
}

struct Concurrent {
    barrier: Arc<Barrier>,
}
impl ArtifactTransport for Concurrent {
    fn open(&self, _: &ArtifactRequest) -> Result<Box<dyn Read + Send>, ModelError> {
        self.barrier.wait();
        Ok(Box::new(Cursor::new(b"abc".to_vec())))
    }
}

#[test]
fn concurrent_publishers_reverify_and_share_the_complete_winner() {
    let temp = tempfile::tempdir().unwrap();
    let cache = ArtifactCache::new(temp.path()).unwrap();
    let declaration = assets("public/model", &[("data", b"abc")]);
    let transport = Concurrent {
        barrier: Arc::new(Barrier::new(2)),
    };
    let (left, right) = std::thread::scope(|scope| {
        let left =
            scope.spawn(|| cache.resolve(&declaration, AcquisitionPolicy::Public, &transport));
        let right =
            scope.spawn(|| cache.resolve(&declaration, AcquisitionPolicy::Public, &transport));
        (
            left.join().unwrap().unwrap(),
            right.join().unwrap().unwrap(),
        )
    });
    assert_eq!(left, right);
    declaration.verify(&left).unwrap();
    no_stages(temp.path());
}

#[test]
fn a_failed_concurrent_download_cleans_only_its_stage_and_preserves_the_winner() {
    use std::sync::{Condvar, Mutex};
    struct FailingRead(Arc<(Mutex<bool>, Condvar)>);
    impl Read for FailingRead {
        fn read(&mut self, _: &mut [u8]) -> io::Result<usize> {
            let (lock, wake) = &*self.0;
            let ready = lock.lock().unwrap();
            let (ready, _) = wake
                .wait_timeout_while(ready, std::time::Duration::from_secs(10), |ready| !*ready)
                .unwrap();
            if !*ready {
                return Err(io::ErrorKind::TimedOut.into());
            }
            Err(io::ErrorKind::UnexpectedEof.into())
        }
    }
    struct Loser {
        opened: Arc<Barrier>,
        ready: Arc<(Mutex<bool>, Condvar)>,
    }
    impl ArtifactTransport for Loser {
        fn open(&self, _: &ArtifactRequest) -> Result<Box<dyn Read + Send>, ModelError> {
            self.opened.wait();
            Ok(Box::new(FailingRead(self.ready.clone())))
        }
    }
    let temp = tempfile::tempdir().unwrap();
    let cache = ArtifactCache::new(temp.path()).unwrap();
    let declaration = assets("public/model", &[("data", b"abc")]);
    let loser = Loser {
        opened: Arc::new(Barrier::new(2)),
        ready: Arc::new((Mutex::new(false), Condvar::new())),
    };
    std::thread::scope(|scope| {
        let failed = scope.spawn(|| cache.resolve(&declaration, AcquisitionPolicy::Public, &loser));
        loser.opened.wait();
        let published = cache
            .resolve(
                &declaration,
                AcquisitionPolicy::Public,
                &Memory::new(&[("data", b"abc")]),
            )
            .unwrap();
        *loser.ready.0.lock().unwrap() = true;
        loser.ready.1.notify_all();
        assert!(failed.join().unwrap().is_err());
        declaration.verify(&published).unwrap();
    });
    no_stages(temp.path());
}

#[cfg(unix)]
#[test]
fn dot_model_components_cannot_escape_and_cache_symlink_substitutions_are_rejected() {
    use std::os::unix::fs::symlink;
    for model in ["../model", "./model", "owner/..", "owner/."] {
        let temp = tempfile::tempdir().unwrap();
        fs::write(temp.path().join("sentinel"), b"keep").unwrap();
        let root = temp.path().join("cache");
        let cache = ArtifactCache::new(&root).unwrap();
        let declaration = assets(model, &[("data", b"abc")]);
        let transport = Memory::new(&[("data", b"abc")]);
        let path = cache
            .resolve(&declaration, AcquisitionPolicy::Public, &transport)
            .unwrap();
        assert_eq!(path, ready(&root, &declaration));
        assert_eq!(fs::read(temp.path().join("sentinel")).unwrap(), b"keep");
    }
    for location in ["root", "models", "final", "artifact"] {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().join("cache");
        let cache = ArtifactCache::new(&root).unwrap();
        let declaration = assets("public/model", &[("data", b"abc")]);
        let transport = Memory::new(&[("data", b"abc")]);
        let published = cache
            .resolve(&declaration, AcquisitionPolicy::Public, &transport)
            .unwrap();
        let target = match location {
            "root" => root.clone(),
            "models" => root.join("models"),
            "final" => published.clone(),
            _ => published.join("data"),
        };
        let moved = temp.path().join("original");
        fs::rename(&target, &moved).unwrap();
        symlink(&moved, &target).unwrap();
        assert!(
            cache
                .resolve(&declaration, AcquisitionPolicy::Offline, &transport)
                .is_err(),
            "{location}"
        );
        if location == "root" {
            assert!(ArtifactCache::new(&root).is_err());
        }
        assert!(moved.exists());
    }
}

#[cfg(unix)]
#[test]
fn stage_swapped_for_a_symlink_cannot_write_or_clean_unrelated_files() {
    struct Swap {
        root: std::path::PathBuf,
        outside: std::path::PathBuf,
    }
    impl ArtifactTransport for Swap {
        fn open(&self, _: &ArtifactRequest) -> Result<Box<dyn Read + Send>, ModelError> {
            let model = fs::read_dir(self.root.join("models"))
                .unwrap()
                .next()
                .unwrap()
                .unwrap()
                .path();
            let stage = fs::read_dir(model)
                .unwrap()
                .find_map(|entry| {
                    let p = entry.unwrap().path();
                    p.file_name()
                        .unwrap()
                        .to_str()
                        .unwrap()
                        .starts_with("ken-artifacts-")
                        .then_some(p)
                })
                .unwrap();
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(&stage).unwrap().permissions().mode() & 0o777,
                0o700
            );
            fs::rename(&stage, self.root.join("displaced-owned-stage")).unwrap();
            std::os::unix::fs::symlink(&self.outside, &stage).unwrap();
            Ok(Box::new(Cursor::new(b"abc".to_vec())))
        }
    }
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("cache");
    let outside = temp.path().join("outside");
    fs::create_dir(&outside).unwrap();
    fs::write(outside.join("sentinel"), b"keep").unwrap();
    let declaration = assets("public/model", &[("data", b"abc")]);
    let cache = ArtifactCache::new(&root).unwrap();
    assert!(
        cache
            .resolve(
                &declaration,
                AcquisitionPolicy::Public,
                &Swap {
                    root: root.clone(),
                    outside: outside.clone()
                }
            )
            .is_err()
    );
    assert_eq!(fs::read(outside.join("sentinel")).unwrap(), b"keep");
    assert!(!outside.join("data").exists());
    assert!(!ready(&root, &declaration).exists());
}
