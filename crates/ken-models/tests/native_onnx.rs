use ken_models::NativeOnnxRuntime;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
};

fn manifest() -> Value {
    serde_json::from_str(include_str!("../resources/onnx-runtime-libraries.json")).unwrap()
}

fn current(value: &mut Value) -> &mut Value {
    value["libraries"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|r| r["os"] == std::env::consts::OS && r["arch"] == std::env::consts::ARCH)
        .unwrap()
}

fn library() -> PathBuf {
    let path = PathBuf::from(
        std::env::var_os("KEN_ORT_LIBRARY")
            .expect("prepare explicit KEN_ORT_LIBRARY before native runtime tests"),
    );
    assert!(path.is_absolute() && path.is_file());
    path
}

fn declare(path: &Path) -> NativeOnnxRuntime {
    NativeOnnxRuntime::from_json(&manifest().to_string(), path).unwrap()
}

fn registration_for(path: &Path) -> Value {
    let mut value = manifest();
    let bytes = fs::read(path).unwrap();
    current(&mut value)["bytes"] = json!(bytes.len());
    current(&mut value)["sha256"] = json!(format!("{:x}", Sha256::digest(bytes)));
    value
}

#[test]
fn declaration_is_lazy_and_rejects_ambiguous_or_unsupported_pins() {
    let dir = tempfile::tempdir().unwrap();
    let absent = dir.path().join("absent-core");
    let runtime = declare(&absent);
    assert!(runtime.loaded_identity().unwrap().is_none());
    assert!(runtime.load().is_err());
    assert!(
        NativeOnnxRuntime::from_json(&manifest().to_string(), Path::new("relative-core")).is_err()
    );
    let mut duplicate = manifest();
    let record = current(&mut duplicate).clone();
    duplicate["libraries"].as_array_mut().unwrap().push(record);
    assert!(NativeOnnxRuntime::from_json(&duplicate.to_string(), &absent).is_err());
    for (field, bad) in [
        ("api", json!(31)),
        ("version", json!("bogus")),
        ("sha256", json!("NOT-A-HASH")),
        ("bytes", json!(u64::MAX)),
    ] {
        let mut value = manifest();
        current(&mut value)[field] = bad;
        assert!(
            NativeOnnxRuntime::from_json(&value.to_string(), &absent).is_err(),
            "{field}"
        );
    }
    let mut value = manifest();
    value["format"] = json!("future/2");
    assert!(NativeOnnxRuntime::from_json(&value.to_string(), &absent).is_err());
}

#[test]
fn authenticated_runtime_reuses_identity_and_verifies_new_aliases() {
    let original = library();
    let runtime = declare(&original);
    assert!(runtime.loaded_identity().unwrap().is_none());
    let identity = runtime.load().unwrap();
    assert_eq!(runtime.loaded_identity().unwrap(), Some(identity.clone()));
    assert_eq!(identity.version, "1.25.1");
    assert_eq!(identity.api, 25);
    let expected = current(&mut manifest()).clone();
    assert_eq!(serde_json::to_value(&identity).unwrap(), expected);
    assert_eq!(runtime.load().unwrap(), identity);
    let dir = tempfile::tempdir().unwrap();
    let alias = dir.path().join("alias-core");
    fs::copy(&original, &alias).unwrap();
    let other = declare(&alias);
    assert_eq!(other.load().unwrap(), identity);
    fs::remove_file(&alias).unwrap();
    assert_eq!(
        other.load().unwrap(),
        identity,
        "authenticated handle must own its lifetime"
    );
    assert!(
        declare(&alias).load().is_err(),
        "a new missing alias cannot borrow warm verification"
    );
    fs::write(&alias, b"corrupt").unwrap();
    assert!(declare(&alias).load().is_err());
    let mut damaged = fs::read(&original).unwrap();
    damaged[0] ^= 1;
    fs::write(&alias, damaged).unwrap();
    assert!(
        declare(&alias).load().is_err(),
        "same-size corruption must be hashed even when warm"
    );
    let threads: Vec<_> = (0..8)
        .map(|_| {
            let runtime = runtime.clone();
            std::thread::spawn(move || runtime.load().unwrap())
        })
        .collect();
    for thread in threads {
        assert_eq!(thread.join().unwrap(), identity);
    }
    let mut bytes = fs::read(original).unwrap();
    bytes.push(0);
    fs::write(&alias, bytes).unwrap();
    let conflict =
        NativeOnnxRuntime::from_json(&registration_for(&alias).to_string(), &alias).unwrap();
    assert!(
        conflict
            .load()
            .unwrap_err()
            .to_string()
            .contains("conflict")
    );
}

#[test]
fn malformed_native_apis_and_foreign_initialization_fail_in_clean_processes() {
    for scenario in ["bad-api", "foreign", "race"] {
        let output = Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "runtime_child", "--nocapture"])
            .env("KEN_NATIVE_RUNTIME_SCENARIO", scenario)
            .env("ORT_DYLIB_PATH", "/not-an-implicit-library")
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{scenario}: {}\n{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
    }
}

fn stub(directory: &Path, scenario: &str) -> PathBuf {
    let body = if scenario == "missing" {
        "pub fn no_native_api() {}".into()
    } else {
        let version = if scenario == "version" {
            "b\"0.0.0\\0\".as_ptr().cast()"
        } else if scenario == "null-version" {
            "std::ptr::null()"
        } else {
            "b\"1.25.1\\0\".as_ptr().cast()"
        };
        let base = if scenario == "null-base" {
            "std::ptr::null()"
        } else {
            "&BASE"
        };
        r#"use std::ffi::{c_char,c_void};
#[repr(C)] pub struct Base { get_api: extern "C" fn(u32)->*const c_void, version: extern "C" fn()->*const c_char }
extern "C" fn get_api(_:u32)->*const c_void { std::ptr::null() }
extern "C" fn version()->*const c_char { VERSION }
static BASE:Base=Base{get_api,version};
#[unsafe(export_name="OrtGetApiBase")] pub extern "C" fn base()->*const Base { BASE_VALUE }
"#.replace("VERSION",version).replace("BASE_VALUE",base)
    };
    let source = directory.join(format!("{scenario}.rs"));
    fs::write(&source, body).unwrap();
    let binary = directory.join(format!("{scenario}.{}", std::env::consts::DLL_EXTENSION));
    let result = Command::new("rustc")
        .args([
            "--edition=2024",
            "--crate-name",
            "native_stub",
            "--crate-type=cdylib",
        ])
        .arg(source)
        .arg("-o")
        .arg(&binary)
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    binary
}

#[test]
fn runtime_child() {
    let Ok(scenario) = std::env::var("KEN_NATIVE_RUNTIME_SCENARIO") else {
        return;
    };
    let original = library();
    if scenario == "bad-api" {
        let dir = tempfile::tempdir().unwrap();
        for (name, expected) in [
            ("missing", "OrtGetApiBase"),
            ("null-base", "null native API base"),
            ("null-version", "null native version"),
            ("version", "version mismatch"),
            ("null-api", "API25 unavailable"),
        ] {
            let path = stub(dir.path(), name);
            let runtime =
                NativeOnnxRuntime::from_json(&registration_for(&path).to_string(), &path).unwrap();
            let error = runtime.load().unwrap_err().to_string();
            assert!(error.contains(expected), "{name}: {error}");
        }
        declare(&original).load().unwrap(); // Failed validation must not poison initialization.
    } else if scenario == "foreign" {
        // SAFETY: test preparation supplies the pinned real core; the leaked
        // handle keeps its API alive until this isolated child process exits.
        let handle = unsafe { libloading::Library::new(&original).unwrap() };
        let api = unsafe {
            let get: libloading::Symbol<unsafe extern "C" fn() -> *const ort::sys::OrtApiBase> =
                handle.get(b"OrtGetApiBase").unwrap();
            let base = get();
            assert!(!base.is_null());
            let api = ((*base).GetApi)(25);
            assert!(!api.is_null());
            (*api).clone()
        };
        assert!(ort::set_api(api));
        std::mem::forget(handle);
        assert!(
            declare(&original)
                .load()
                .unwrap_err()
                .to_string()
                .contains("already")
        );
    } else if scenario == "race" {
        let dir = tempfile::tempdir().unwrap();
        let aliases: Vec<_> = (0..8)
            .map(|index| {
                let path = dir.path().join(format!("core-{index}"));
                fs::copy(&original, &path).unwrap();
                path
            })
            .collect();
        let threads: Vec<_> = (0..8)
            .map(|index| {
                let path = aliases[index].clone();
                std::thread::spawn(move || declare(&path).load().unwrap())
            })
            .collect();
        let identities: Vec<_> = threads.into_iter().map(|t| t.join().unwrap()).collect();
        assert!(identities.iter().all(|i| i == &identities[0]));
    } else {
        panic!("unknown runtime child scenario");
    }
}
