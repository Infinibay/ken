use ken_daemon::client::{Client, ClientOptions, Program};
use serde_json::json;
#[test]
fn stopping_an_absent_or_stale_daemon_never_spawns_or_mutates_advertisement() {
    let root = tempfile::tempdir().unwrap();
    std::fs::create_dir(root.path().join(".ken")).unwrap();
    std::fs::write(
        root.path().join(".ken/meta.json"),
        json!({"auth_token":"native-test"}).to_string(),
    )
    .unwrap();
    let client = Client::new(
        root.path(),
        Program::new(root.path().join("must-not-execute")),
        ClientOptions::default(),
    );
    assert!(
        client
            .post_existing("/shutdown", &json!({}))
            .unwrap()
            .is_none()
    );
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    drop(listener);
    std::fs::write(root.path().join(".ken/daemon.port"), port.to_string()).unwrap();
    assert!(
        client
            .post_existing("/shutdown", &json!({}))
            .unwrap()
            .is_none()
    );
    assert_eq!(
        std::fs::read_to_string(root.path().join(".ken/daemon.port")).unwrap(),
        port.to_string()
    );
    assert!(!root.path().join(".ken/daemon.log").exists());
    assert!(!root.path().join(".ken/daemon.spawn.lock").exists());
}
