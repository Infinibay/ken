//! Real C ABI fixture; no inference/model acceptance is derived from these tests.
use ken_native_model_api::{
    GetApiV1, KenBuffer, KenBytes, MAX_DIAGNOSTIC, MAX_PAYLOAD, api_table, checked_bytes,
};
use libloading::Library;
use serde_json::{Value, json};
use std::{
    path::{Path, PathBuf},
    process::Command,
    sync::OnceLock,
};

const FIXTURE_BACKEND: u32 = 0xffff_fffe;

fn fixture() -> &'static Path {
    static BINARY: OnceLock<PathBuf> = OnceLock::new();
    BINARY.get_or_init(|| {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap();
        let target = root.join(".ken/rust-migration/m2-optional/api-fixture-target");
        let status = Command::new(env!("CARGO"))
            .args(["build", "--offline", "--manifest-path"])
            .arg(root.join("native/ken-model-test-backend/Cargo.toml"))
            .env("CARGO_TARGET_DIR", &target)
            .status()
            .unwrap();
        assert!(
            status.success(),
            "native contract fixture must build; no missing-dependency skip"
        );
        target.join("debug").join(format!(
            "{}ken_model_test_backend{}",
            std::env::consts::DLL_PREFIX,
            std::env::consts::DLL_SUFFIX
        ))
    })
}

#[test]
fn actual_native_boundary_rejects_bad_handles_catches_panics_and_releases_buffers() {
    let directory = tempfile::tempdir().unwrap();
    let log = directory.path().join("lifecycle.jsonl");
    // SAFETY: the fixture is built from this test's known source; this owner
    // stays live through every table/model/buffer call and all cleanup.
    let library = unsafe { Library::new(fixture()) }.unwrap();
    let getter: libloading::Symbol<GetApiV1> =
        unsafe { library.get(b"ken_model_api_v1\0") }.unwrap();
    let table = unsafe { api_table(getter(), FIXTURE_BACKEND) }.unwrap();
    let open = table.open.unwrap();
    let run = table.run.unwrap();
    let close = table.close.unwrap();
    let release = table.release.unwrap();
    let mut handle = 0;
    let mut output = KenBuffer::EMPTY;
    let request = serde_json::to_vec(&json!({"factor":2.0,"lifecycle_log":log})).unwrap();
    assert_eq!(
        unsafe { open(KenBytes::new(&request).unwrap(), &mut handle, &mut output) },
        0
    );
    assert_ne!(handle, 0);
    assert_eq!(unsafe { release(&mut output) }, 0);
    assert_ne!(
        unsafe {
            run(
                handle,
                KenBytes {
                    ptr: std::ptr::null(),
                    len: 1,
                },
                &mut output,
            )
        },
        0
    );
    assert_eq!(unsafe { release(&mut output) }, 0);
    assert_ne!(
        unsafe {
            run(
                handle,
                KenBytes {
                    ptr: std::ptr::NonNull::dangling().as_ptr(),
                    len: MAX_PAYLOAD + 1,
                },
                &mut output,
            )
        },
        0
    );
    assert_eq!(unsafe { release(&mut output) }, 0);
    let duplicate = br#"{"operation":"scale","operation":"panic","values":[]}"#;
    assert_ne!(
        unsafe { run(handle, KenBytes::new(duplicate).unwrap(), &mut output) },
        0
    );
    assert_eq!(unsafe { release(&mut output) }, 0);
    let request = br#"{"operation":"scale","values":[1.0,3.0]}"#;
    assert_eq!(
        unsafe { run(handle, KenBytes::new(request).unwrap(), &mut output) },
        0
    );
    let raw = unsafe {
        checked_bytes(
            KenBytes {
                ptr: output.ptr,
                len: output.len,
            },
            MAX_PAYLOAD,
        )
    }
    .unwrap();
    let values: Value = serde_json::from_slice(raw).unwrap();
    assert_eq!(values["values"], json!([2.0, 6.0]));
    assert_eq!(values["scope"], "contract-fixture");
    let mut stale = output;
    assert_eq!(unsafe { release(&mut output) }, 0);
    assert_ne!(unsafe { release(&mut stale) }, 0);
    let panic = br#"{"operation":"panic","values":[]}"#;
    assert_ne!(
        unsafe { run(handle, KenBytes::new(panic).unwrap(), &mut output) },
        0
    );
    assert!(output.len > 0 && output.len <= MAX_DIAGNOSTIC);
    assert_eq!(unsafe { release(&mut output) }, 0);
    assert_eq!(
        unsafe { run(handle, KenBytes::new(request).unwrap(), &mut output) },
        0
    );
    assert_eq!(unsafe { release(&mut output) }, 0);
    assert_eq!(unsafe { close(handle) }, 0);
    assert_ne!(unsafe { close(handle) }, 0);
    assert_ne!(
        unsafe { run(handle, KenBytes::new(request).unwrap(), &mut output) },
        0
    );
    assert_eq!(unsafe { release(&mut output) }, 0);
    let events: Vec<Value> = std::fs::read_to_string(log)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    let closed = events
        .iter()
        .position(|event| event["event"] == "model_closed")
        .unwrap();
    assert!(
        events[..closed]
            .iter()
            .filter(|event| event["event"] == "buffer_released")
            .count()
            >= 3
    );
}
