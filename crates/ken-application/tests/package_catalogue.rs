//! Catalogue declarations are part of the portable authenticated resource closure.
#[path = "support/native_package.rs"]
mod support;
use ken_application::package::PackageApplication;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{fs, path::Path};
fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn metadata(bundle: &Path, declaration: Value) {
    let path = bundle.join("resources/search.json");
    let mut raw: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
    raw["catalogue_extensions"] = declaration;
    support::replace(
        bundle,
        "resources/search.json",
        &serde_json::to_vec(&raw).unwrap(),
        0o444,
    );
}
#[test]
fn portable_catalogue_declaration_binds_one_owned_inventory_file() {
    let temp = tempfile::tempdir().unwrap();
    let bundle = temp.path().join("bundle");
    support::bundle(&bundle, Path::new("/bin/true"), None);
    let bytes = b"contract fixture, not a qualified model recipe";
    fs::write(bundle.join("resources/catalogue.json"), bytes).unwrap();
    support::replace(&bundle, "resources/catalogue.json", bytes, 0o444);
    metadata(
        &bundle,
        json!({"path":"catalogue.json","bytes":bytes.len(),"sha256":hash(bytes)}),
    );
    let app = PackageApplication::new(&temp.path().join("prefix")).unwrap();
    assert!(app.authenticate(&bundle).is_ok());
}
#[test]
fn external_missing_or_inventory_inconsistent_catalogues_fail_before_activation() {
    for kind in ["absolute", "traversal", "undeclared", "bytes", "sha256"] {
        let temp = tempfile::tempdir().unwrap();
        let bundle = temp.path().join("bundle");
        support::bundle(&bundle, Path::new("/bin/true"), None);
        let bytes = b"catalogue fixture";
        fs::write(bundle.join("resources/catalogue.json"), bytes).unwrap();
        support::replace(&bundle, "resources/catalogue.json", bytes, 0o444);
        let external = temp.path().join("catalogue.json");
        fs::write(&external, bytes).unwrap();
        let mut declaration =
            json!({"path":"catalogue.json","bytes":bytes.len(),"sha256":hash(bytes)});
        match kind {
            "absolute" => declaration["path"] = json!(external),
            "traversal" => declaration["path"] = json!("../../catalogue.json"),
            "undeclared" => declaration["path"] = json!("missing.json"),
            "bytes" => declaration["bytes"] = json!(bytes.len() + 1),
            "sha256" => declaration["sha256"] = json!("0".repeat(64)),
            _ => unreachable!(),
        }
        metadata(&bundle, declaration);
        let prefix = temp.path().join("prefix");
        let app = PackageApplication::new(&prefix).unwrap();
        assert!(app.authenticate(&bundle).is_err(), "accepted {kind}");
        assert!(!prefix.exists());
    }
}
