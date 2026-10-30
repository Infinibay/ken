use ken_daemon::{
    client::{Client, ClientOptions, Program},
    server::{self, DaemonConfig},
    state::DaemonState,
};
use ken_retrieval::query_encoder::QueryEncoder;
use std::{
    rc::Rc,
    time::{Duration, Instant},
};
struct Encoder;
impl QueryEncoder for Encoder {
    fn embed_query(&self, _: &ken_text::PythonText) -> ken_retrieval::Result<Vec<f32>> {
        Ok(vec![1., 0.])
    }
}
#[test]
fn shutdown_waits_for_native_runtime_ownership_and_persistent_session_finalization() {
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir(root.path().join(".ken")).unwrap();
    std::fs::write(
        root.path().join(".ken/meta.json"),
        r#"{"project_id":"shutdown","auth_token":"token"}"#,
    )
    .unwrap();
    let path = root.path().to_owned();
    let server = std::thread::spawn(move || {
        let state = DaemonState::open(
            &path,
            Rc::new(Encoder),
            Box::new(ken_context::NativeNumerics::default()),
            ken_context::Policy::default(),
        )
        .unwrap();
        server::serve(DaemonConfig::new(&path), state, None).unwrap();
    });
    let client = Client::new(
        root.path(),
        Program::new(root.path().join("must-not-spawn")),
        ClientOptions::default(),
    );
    let deadline = Instant::now() + Duration::from_secs(5);
    while client.health().is_none() {
        assert!(Instant::now() < deadline);
        std::thread::yield_now();
    }
    client
        .post_existing(
            "/sessions/start",
            &serde_json::json!({"session_id":"active-native"}),
        )
        .unwrap();
    client.stop_existing().unwrap();
    assert!(client.health().is_none());
    assert!(!root.path().join(".ken/daemon.port").exists());
    assert!(!root.path().join(".ken/daemon.pid").exists());
    server.join().unwrap();
    let db = rusqlite::Connection::open(root.path().join(".ken/ken.db")).unwrap();
    let ended:i64=db.query_row("SELECT count(*) FROM cr_sessions WHERE agent_id='active-native' AND ended_at IS NOT NULL",[],|r|r.get(0)).unwrap();
    assert_eq!(ended, 1);
    client.stop_existing().unwrap();
    assert!(!root.path().join(".ken/daemon.spawn.lock").exists());
}
#[test]
fn shutdown_refuses_a_live_owner_that_does_not_respond_instead_of_clearing_or_spawn() {
    use std::os::{fd::AsRawFd, unix::fs::OpenOptionsExt};
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir(root.path().join(".ken")).unwrap();
    let lock = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(root.path().join(".ken/daemon.lock"))
        .unwrap();
    assert_eq!(
        unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) },
        0
    );
    let options = ClientOptions {
        spawn_timeout: Duration::from_millis(40),
        poll_interval: Duration::from_millis(5),
        ..Default::default()
    };
    let client = Client::new(
        root.path(),
        Program::new(root.path().join("must-not-spawn")),
        options,
    );
    assert!(client.stop_existing().is_err());
    assert!(!root.path().join(".ken/daemon.spawn.lock").exists());
}
