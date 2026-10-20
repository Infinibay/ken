use ken_models::{ModelAssets, ModelFileSource};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{fs, path::Path};

const REVISION: &str = "1111111111111111111111111111111111111111";

fn assets(files: &[(&str, &[u8])]) -> ModelAssets {
    let artifacts: serde_json::Map<String, serde_json::Value> = files
        .iter()
        .map(|(name, data)| {
            (
                name.to_string(),
                json!({"bytes":data.len(),"sha256":format!("{:x}",Sha256::digest(data))}),
            )
        })
        .collect();
    ModelAssets::from_json(
        &json!({"model_id":"test/files","revision":REVISION,
        "license":"mit","artifacts":artifacts})
        .to_string(),
    )
    .unwrap()
}

fn fixture(root: &Path) -> (std::path::PathBuf, std::path::PathBuf) {
    let snapshot = root.join(REVISION);
    let private = root.join("private");
    fs::create_dir(&snapshot).unwrap();
    fs::create_dir(&private).unwrap();
    (snapshot, private)
}

#[test]
fn private_copy_survives_source_replacement_and_drops_its_files() {
    let temp = tempfile::tempdir().unwrap();
    let (snapshot, private) = fixture(temp.path());
    fs::create_dir(snapshot.join("nested")).unwrap();
    fs::write(snapshot.join("nested/weights.bin"), b"abc").unwrap();
    let registration = assets(&[("nested/weights.bin", b"abc")]);
    let source = ModelFileSource::new(&snapshot, &private).unwrap();
    assert_eq!(
        fs::read_dir(&private).unwrap().count(),
        0,
        "construction stays lazy"
    );
    let verified = registration.verify_files(&source).unwrap();
    assert_eq!(verified.fingerprint(), registration.fingerprint());
    let owned_root = fs::read_dir(&private)
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    let owned = owned_root.join("nested/weights.bin");
    #[cfg(unix)]
    {
        use std::os::unix::fs::{MetadataExt, PermissionsExt};
        assert_ne!(
            fs::metadata(&owned).unwrap().ino(),
            fs::metadata(snapshot.join("nested/weights.bin"))
                .unwrap()
                .ino()
        );
        for directory in [&owned_root, &owned_root.join("nested")] {
            assert_eq!(
                fs::metadata(directory).unwrap().permissions().mode() & 0o777,
                0o700
            );
        }
        assert_eq!(
            fs::metadata(&owned).unwrap().permissions().mode() & 0o777,
            0o444
        );
    }
    fs::write(snapshot.join("replacement"), b"abd").unwrap();
    fs::rename(
        snapshot.join("replacement"),
        snapshot.join("nested/weights.bin"),
    )
    .unwrap();
    assert_eq!(verified.read("nested/weights.bin").unwrap(), b"abc");
    assert!(verified.read("../weights.bin").is_err());
    assert!(verified.read("unknown").is_err());
    assert!(registration.verify_files(&source).is_err());
    fs::remove_dir_all(&snapshot).unwrap();
    assert_eq!(verified.read("nested/weights.bin").unwrap(), b"abc");
    drop(verified);
    assert!(!owned_root.exists());
    assert_eq!(fs::read_dir(&private).unwrap().count(), 0);
}

#[test]
fn failed_partial_copy_does_not_publish_or_leave_a_directory() {
    let temp = tempfile::tempdir().unwrap();
    let (snapshot, private) = fixture(temp.path());
    fs::write(snapshot.join("a.bin"), b"abc").unwrap();
    fs::write(snapshot.join("z.bin"), b"abd").unwrap();
    let registration = assets(&[("a.bin", b"abc"), ("z.bin", b"abc")]);
    let source = ModelFileSource::new(&snapshot, &private).unwrap();
    assert!(registration.verify_files(&source).is_err());
    assert_eq!(fs::read_dir(&private).unwrap().count(), 0);
    fs::write(snapshot.join("z.bin"), b"ab").unwrap();
    assert!(registration.verify_files(&source).is_err());
    assert_eq!(fs::read_dir(&private).unwrap().count(), 0);
    fs::write(snapshot.join("z.bin"), b"abc").unwrap();
    assert_eq!(
        registration
            .verify_files(&source)
            .unwrap()
            .read("z.bin")
            .unwrap(),
        b"abc"
    );
}

#[test]
fn explicit_absolute_paths_and_registered_revision_are_required() {
    let temp = tempfile::tempdir().unwrap();
    let (snapshot, private) = fixture(temp.path());
    assert!(ModelFileSource::new(Path::new("relative"), &private).is_err());
    assert!(ModelFileSource::new(&snapshot, Path::new("relative")).is_err());
    let wrong = temp.path().join("wrong");
    fs::create_dir(&wrong).unwrap();
    fs::write(wrong.join("weights.bin"), b"abc").unwrap();
    let source = ModelFileSource::new(&wrong, &private).unwrap();
    assert!(
        assets(&[("weights.bin", b"abc")])
            .verify_files(&source)
            .is_err()
    );
    assert_eq!(fs::read_dir(&private).unwrap().count(), 0);
}

#[cfg(unix)]
#[test]
fn source_blob_symlinks_are_copied_as_independent_regular_files() {
    use std::os::unix::fs::MetadataExt;
    let temp = tempfile::tempdir().unwrap();
    let (snapshot, private) = fixture(temp.path());
    let blob = temp.path().join("blob");
    fs::write(&blob, b"abc").unwrap();
    std::os::unix::fs::symlink(&blob, snapshot.join("weights.bin")).unwrap();
    let source = ModelFileSource::new(&snapshot, &private).unwrap();
    let owned = assets(&[("weights.bin", b"abc")])
        .verify_files(&source)
        .unwrap();
    let copied = fs::read_dir(&private)
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path()
        .join("weights.bin");
    assert!(fs::symlink_metadata(&copied).unwrap().is_file());
    assert_ne!(
        fs::metadata(&copied).unwrap().ino(),
        fs::metadata(&blob).unwrap().ino()
    );
    fs::write(&blob, b"abd").unwrap();
    assert_eq!(owned.read("weights.bin").unwrap(), b"abc");
}

#[cfg(unix)]
#[test]
fn device_source_is_rejected_even_for_empty_matching_bytes() {
    let temp = tempfile::tempdir().unwrap();
    let (snapshot, private) = fixture(temp.path());
    std::os::unix::fs::symlink("/dev/null", snapshot.join("weights.bin")).unwrap();
    let source = ModelFileSource::new(&snapshot, &private).unwrap();
    assert!(
        assets(&[("weights.bin", b"")])
            .verify_files(&source)
            .is_err()
    );
    assert_eq!(fs::read_dir(&private).unwrap().count(), 0);
}

#[cfg(unix)]
#[test]
fn fifo_copy_does_not_wait_for_a_writer() {
    use std::{
        ffi::CString,
        process::Command,
        time::{Duration, Instant},
    };
    let temp = tempfile::tempdir().unwrap();
    let (snapshot, _) = fixture(temp.path());
    let name = CString::new(snapshot.join("weights.bin").as_os_str().as_encoded_bytes()).unwrap();
    // SAFETY: this owned NUL-terminated path names only the test FIFO.
    assert_eq!(unsafe { libc::mkfifo(name.as_ptr(), 0o600) }, 0);
    let mut child = Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "fifo_copy_child", "--nocapture"])
        .env("KEN_FILE_COPY_FIFO", temp.path())
        .spawn()
        .unwrap();
    let deadline = Instant::now() + Duration::from_secs(3);
    loop {
        if let Some(status) = child.try_wait().unwrap() {
            assert!(status.success());
            break;
        }
        if Instant::now() >= deadline {
            child.kill().unwrap();
            child.wait().unwrap();
            panic!("FIFO copy blocked");
        }
        std::thread::sleep(Duration::from_millis(5));
    }
}

#[cfg(unix)]
#[test]
fn fifo_copy_child() {
    let Some(root) = std::env::var_os("KEN_FILE_COPY_FIFO") else {
        return;
    };
    let root = Path::new(&root);
    let source = ModelFileSource::new(&root.join(REVISION), &root.join("private")).unwrap();
    assert!(
        assets(&[("weights.bin", b"")])
            .verify_files(&source)
            .is_err()
    );
}
