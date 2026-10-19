use ken_models::ModelAssets;
use serde_json::{Value, json};

fn registration() -> Value {
    json!({"model_id":"test/static", "revision":"1111111111111111111111111111111111111111",
        "license":"Español 🙂", "artifacts":{"weights.bin":{"bytes":3,
        "sha256":"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"}}})
}

#[test]
fn fingerprint_matches_python_ascii_sorted_identity() {
    let assets = ModelAssets::from_json(&registration().to_string()).unwrap();
    assert_eq!(
        assets.fingerprint(),
        "11995e883b97430e0b4f0d20c736d9298afc20ec83bbb603a0429fdcd1f9ceed"
    );
    let real = ModelAssets::from_json(include_str!(
        "../../../src/ken/embedder/data/potion-code-16M-v2.json"
    ))
    .unwrap();
    assert_eq!(
        real.fingerprint(),
        "358803c97ebfa214e3cc325cfb1c8d0e4ceaf38d060676a7c2e40f9204c1589e"
    );
}

#[test]
fn rejects_ambiguous_or_unsafe_registrations() {
    for name in [
        "",
        "/tmp/weights",
        ".",
        "..",
        "../weights",
        "a//b",
        "a/./b",
        "a/../b",
        "a\\b",
        "café",
    ] {
        let mut value = registration();
        value["artifacts"] = json!({name: {"bytes":3,"sha256":"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"}});
        assert!(
            ModelAssets::from_json(&value.to_string()).is_err(),
            "{name}"
        );
    }
    for (key, invalid) in [
        ("revision", "main"),
        ("revision", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
        ("model_id", "https://private/model"),
    ] {
        let mut value = registration();
        value[key] = json!(invalid);
        assert!(ModelAssets::from_json(&value.to_string()).is_err());
    }
    for invalid in [json!(-1), json!(true), json!(3.0)] {
        let mut value = registration();
        value["artifacts"]["weights.bin"]["bytes"] = invalid;
        assert!(ModelAssets::from_json(&value.to_string()).is_err());
    }
    let mut value = registration();
    value["artifacts"]["weights.bin"]["sha256"] = json!("BAD");
    assert!(ModelAssets::from_json(&value.to_string()).is_err());
    value["artifacts"] = json!({});
    assert!(ModelAssets::from_json(&value.to_string()).is_err());
    let duplicate = r#"{"model_id":"test/static","revision":"1111111111111111111111111111111111111111","artifacts":{"x":{"bytes":0,"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},"x":{"bytes":0,"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}}}"#;
    assert!(ModelAssets::from_json(duplicate).is_err());
}

#[test]
fn verified_snapshot_owns_the_accredited_bytes() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("1111111111111111111111111111111111111111");
    std::fs::create_dir(&root).unwrap();
    std::fs::write(root.join("weights.bin"), b"abc").unwrap();
    let assets = ModelAssets::from_json(&registration().to_string()).unwrap();
    let verified = assets.verify(&root).unwrap();
    std::fs::write(root.join("weights.bin"), b"abd").unwrap();
    assert_eq!(verified.artifact("weights.bin").unwrap(), b"abc");
    assert!(verified.artifact("unknown").is_err());
    assert!(assets.verify(&root).is_err());
    std::fs::write(root.join("weights.bin"), b"ab").unwrap();
    assert!(assets.verify(&root).is_err());
    assert!(assets.verify(dir.path()).is_err());
}

#[cfg(unix)]
#[test]
fn accepts_huggingface_blob_symlinks() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("1111111111111111111111111111111111111111");
    std::fs::create_dir(&root).unwrap();
    std::fs::write(dir.path().join("blob"), b"abc").unwrap();
    std::os::unix::fs::symlink("../blob", root.join("weights.bin")).unwrap();
    let assets = ModelAssets::from_json(&registration().to_string()).unwrap();
    assert_eq!(
        assets
            .verify(&root)
            .unwrap()
            .artifact("weights.bin")
            .unwrap(),
        b"abc"
    );
}

#[cfg(unix)]
#[test]
fn rejects_nonregular_device_even_when_size_and_hash_match() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("1111111111111111111111111111111111111111");
    std::fs::create_dir(&root).unwrap();
    std::os::unix::fs::symlink("/dev/null", root.join("weights.bin")).unwrap();
    let mut value = registration();
    value["artifacts"]["weights.bin"] = json!({"bytes":0,
        "sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"});
    let assets = ModelAssets::from_json(&value.to_string()).unwrap();
    assert!(
        assets.verify(&root).is_err(),
        "a device is not an immutable model artifact"
    );
}

#[cfg(unix)]
#[test]
fn fifo_artifact_verification_does_not_wait_for_a_writer() {
    use std::{
        ffi::CString,
        process::Command,
        time::{Duration, Instant},
    };
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("1111111111111111111111111111111111111111");
    std::fs::create_dir(&root).unwrap();
    let path = CString::new(root.join("weights.bin").as_os_str().as_encoded_bytes()).unwrap();
    // SAFETY: NUL-terminated owned path; mkfifo only creates this test's FIFO.
    assert_eq!(unsafe { libc::mkfifo(path.as_ptr(), 0o600) }, 0);
    let mut child = Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "fifo_verification_child", "--nocapture"])
        .env("KEN_ASSET_FIFO_CASE", &root)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        if let Some(status) = child.try_wait().unwrap() {
            let output = child.wait_with_output().unwrap();
            assert!(
                status.success(),
                "{}",
                String::from_utf8_lossy(&output.stderr)
            );
            break;
        }
        if Instant::now() >= deadline {
            child.kill().unwrap();
            child.wait().unwrap();
            panic!("FIFO verification blocked waiting for a writer");
        }
        std::thread::sleep(Duration::from_millis(5));
    }
}

#[cfg(unix)]
#[test]
fn fifo_verification_child() {
    let Some(root) = std::env::var_os("KEN_ASSET_FIFO_CASE") else {
        return;
    };
    let assets = ModelAssets::from_json(&registration().to_string()).unwrap();
    assert!(assets.verify(std::path::Path::new(&root)).is_err());
}

#[test]
fn maximal_declared_size_returns_error_without_allocation() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().join("1111111111111111111111111111111111111111");
    std::fs::create_dir(&root).unwrap();
    std::fs::write(root.join("weights.bin"), b"abc").unwrap();
    let mut value = registration();
    value["artifacts"]["weights.bin"]["bytes"] = json!(u64::MAX);
    assert!(
        ModelAssets::from_json(&value.to_string())
            .unwrap()
            .verify(&root)
            .is_err()
    );
}
