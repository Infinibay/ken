//! Run the actual build program against isolated production input trees.
use std::{fs, path::Path, process::Command};
fn put(root: &Path, path: &str, text: &str) {
    let path = root.join(path);
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, text).unwrap();
}
fn prepare(root: &Path) {
    for file in ["Cargo.toml", "Cargo.lock", "rust-toolchain.toml"] {
        put(root, file, "fixed native input");
    }
    for name in [
        "ken-core",
        "ken-program",
        "ken-query",
        "ken-contracts",
        "ken-syntax",
        "ken-store",
        "ken-text",
        "ken-structural",
    ] {
        put(
            root,
            &format!("crates/{name}/src/lib.rs"),
            "fn unchanged() {}",
        );
        put(
            root,
            &format!("crates/{name}/Cargo.toml"),
            "[package]\nversion='0.18.0'",
        );
    }
    put(
        root,
        "crates/ken-structural/build.rs",
        "unchanged build policy",
    );
    put(root, "crates/ken-syntax/grammars.lock.json", "{}");
    put(
        root,
        "crates/ken-program/resources/python-exceptions.json",
        "{}",
    );
    put(
        root,
        "crates/ken-syntax/src/structural/vocabulary.json",
        "{}",
    );
    put(
        root,
        "crates/ken-retrieval/vendor/ruff-python-parser/Cargo.toml",
        "[package]\nversion='0.15.8'",
    );
    put(
        root,
        "crates/ken-retrieval/vendor/ruff-python-parser/src/lib.rs",
        "fn unchanged_parser() {}",
    );
}
fn revision(root: &Path) -> String {
    let out = root.join("generated");
    fs::create_dir_all(&out).unwrap();
    let program = include_str!(concat!(env!("OUT_DIR"), "/identity-program"));
    let result = Command::new(program)
        .env("CARGO_MANIFEST_DIR", root.join("crates/ken-structural"))
        .env("OUT_DIR", &out)
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    fs::read_to_string(out.join("identity.rs")).unwrap()
}
#[test]
fn resources_local_parser_and_feature_manifests_change_native_identity() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path();
    prepare(root);
    let mut previous = revision(root);
    for file in [
        "crates/ken-syntax/src/structural/vocabulary.json",
        "crates/ken-program/resources/python-exceptions.json",
        "crates/ken-retrieval/vendor/ruff-python-parser/src/lib.rs",
        "Cargo.toml",
        "crates/ken-program/Cargo.toml",
        "crates/ken-query/src/lib.rs",
        "crates/ken-contracts/src/lib.rs",
    ] {
        put(root, file, "changed production behavior");
        let changed = revision(root);
        assert_ne!(changed, previous, "identity ignored {file}");
        previous = changed;
    }
}
#[test]
fn fingerprint_is_path_independent_and_new_source_inputs_invalidate_it() {
    let a = tempfile::tempdir().unwrap();
    let b = tempfile::tempdir().unwrap();
    prepare(a.path());
    prepare(b.path());
    assert_eq!(revision(a.path()), revision(b.path()));
    let before = revision(a.path());
    put(
        a.path(),
        "crates/ken-program/src/new_rule.rs",
        "fn new_rule() {}",
    );
    assert_ne!(revision(a.path()), before);
}
