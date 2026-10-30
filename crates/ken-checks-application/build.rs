//! Own application/worker code identity; lower owners provide their identities.
use sha2::{Digest, Sha256};
use std::{
    fs,
    path::{Path, PathBuf},
};
fn collect(path: &Path, out: &mut Vec<PathBuf>) {
    println!("cargo:rerun-if-changed={}", path.display());
    if !path.exists() {
        return;
    }
    if path.is_file() {
        out.push(path.into());
        return;
    }
    let mut paths = fs::read_dir(path)
        .unwrap()
        .map(|e| e.unwrap().path())
        .collect::<Vec<_>>();
    paths.sort();
    for path in paths {
        collect(&path, out);
    }
}
fn main() {
    let root = PathBuf::from(std::env::var_os("CARGO_MANIFEST_DIR").unwrap());
    let mut inputs = Vec::new();
    for name in ["Cargo.toml", "build.rs", "src", "resources"] {
        collect(&root.join(name), &mut inputs);
    }
    let mut hash = Sha256::new();
    for path in inputs {
        let name = path
            .strip_prefix(&root)
            .unwrap()
            .to_str()
            .unwrap()
            .as_bytes();
        let bytes = fs::read(&path).unwrap();
        for value in [name, bytes.as_slice()] {
            hash.update((value.len() as u64).to_be_bytes());
            hash.update(value);
        }
    }
    let fingerprint = format!("{:x}", hash.finalize());
    let out = PathBuf::from(std::env::var_os("OUT_DIR").unwrap());
    fs::write(
        out.join("identity.rs"),
        format!("pub const IMPLEMENTATION_FINGERPRINT:&str={fingerprint:?};"),
    )
    .unwrap();
}
