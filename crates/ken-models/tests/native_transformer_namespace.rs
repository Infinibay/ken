//! Tiny actual ELF/C ABI contracts; no SDK, model weights or numerical corpus.
#![cfg(all(target_os = "linux", target_env = "gnu"))]
use ken_models::NativeTransformerRuntime;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    path::{Path, PathBuf},
    process::Command,
};
fn source() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/transformer-namespace")
}
fn cc(arguments: &[&str]) {
    let output = Command::new("cc").args(arguments).output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
}
fn compile(root: &Path) {
    std::fs::create_dir_all(root.join("host")).unwrap();
    std::fs::create_dir_all(root.join("core/lib")).unwrap();
    let source = source();
    let marker = source.join("marker.c");
    let bridge = source.join("bridge.c");
    let module = source.join("module.c");
    for (value, output) in [
        ("11", root.join("host/libz_collision.so")),
        ("22", root.join("core/lib/libz_collision.so")),
    ] {
        cc(&[
            "-shared",
            "-fPIC",
            "-Wl,-soname,libz_collision.so",
            &format!("-DMARKER={value}"),
            marker.to_str().unwrap(),
            "-o",
            output.to_str().unwrap(),
        ]);
    }
    cc(&[
        "-shared",
        "-fPIC",
        "-Wl,-soname,liba_bridge.so",
        bridge.to_str().unwrap(),
        "-L",
        root.join("core/lib").to_str().unwrap(),
        "-l:libz_collision.so",
        "-Wl,--enable-new-dtags,-rpath,$ORIGIN",
        "-o",
        root.join("core/lib/liba_bridge.so").to_str().unwrap(),
    ]);
    cc(&[
        "-shared",
        "-fPIC",
        module.to_str().unwrap(),
        "-L",
        root.join("core/lib").to_str().unwrap(),
        "-l:liba_bridge.so",
        "-Wl,--allow-shlib-undefined,--enable-new-dtags,-rpath,$ORIGIN/lib",
        "-o",
        root.join("core/module.so").to_str().unwrap(),
    ]);
}
fn hash(path: &Path) -> Value {
    let bytes = std::fs::read(path).unwrap();
    json!({"bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(bytes))})
}
fn runtime(root: &Path) -> NativeTransformerRuntime {
    let core = root.join("core");
    let module = core.join("module.so");
    NativeTransformerRuntime::from_json(&json!({"format":"ken-native-transformer/1","backend":"torch","runtimes":[{"os":"linux","arch":std::env::consts::ARCH,"core_version":"2.9.0","module":hash(&module),"libraries":{"lib/liba_bridge.so":hash(&core.join("lib/liba_bridge.so")),"lib/libz_collision.so":hash(&core.join("lib/libz_collision.so"))}}]}).to_string(),&module,&core).unwrap()
}
#[test]
fn authenticated_private_dependencies_override_same_soname_and_launcher_search_path() {
    let temp = tempfile::tempdir().unwrap();
    compile(temp.path());
    let output = Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "namespace_probe", "--ignored", "--nocapture"])
        .env("KEN_NAMESPACE_FIXTURE", temp.path())
        .env("LD_LIBRARY_PATH", temp.path().join("host"))
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}
#[test]
fn changed_declared_dependency_is_rejected_before_mapping() {
    let temp = tempfile::tempdir().unwrap();
    compile(temp.path());
    let runtime = runtime(temp.path());
    std::fs::write(temp.path().join("core/lib/libz_collision.so"), b"changed").unwrap();
    assert!(runtime.load().is_err());
    assert!(runtime.loaded_identity().unwrap().is_none());
}
#[test]
#[ignore = "native fixture child; selected by the parent test with a startup loader environment"]
fn namespace_probe() {
    let root = PathBuf::from(std::env::var_os("KEN_NAMESPACE_FIXTURE").unwrap());
    // SAFETY: test-built trusted library; keep the base handle mapped throughout.
    let base = unsafe {
        libloading::os::unix::Library::open(
            Some(root.join("host/libz_collision.so")),
            libc::RTLD_NOW | libc::RTLD_GLOBAL,
        )
    }
    .unwrap();
    let marker =
        unsafe { base.get::<unsafe extern "C" fn() -> i32>(b"ken_namespace_marker\0") }.unwrap();
    assert_eq!(unsafe { marker() }, 11);
    let runtime = runtime(&root);
    let identity = runtime.load().expect(
        "private authenticated dependency must be selected despite host SONAME and LD_LIBRARY_PATH",
    );
    assert_eq!(runtime.load().unwrap(), identity);
    std::fs::remove_dir_all(root.join("core")).unwrap();
    assert_eq!(
        runtime.load().unwrap(),
        identity,
        "live owner keeps private copied code after sources disappear"
    );
    assert_eq!(
        unsafe { marker() },
        11,
        "base namespace must stay unchanged"
    );
}
