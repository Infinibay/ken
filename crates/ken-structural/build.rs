// Cache identity owns the production source/resource and local-dependency closure.
use sha2::{Digest, Sha256};
use std::{
    env, fs,
    path::{Path, PathBuf},
};
fn collect(dir: &Path, paths: &mut Vec<PathBuf>) {
    if !dir.exists() {
        return;
    }
    println!("cargo:rerun-if-changed={}", dir.display());
    let mut entries = fs::read_dir(dir)
        .unwrap()
        .map(|e| e.unwrap().path())
        .collect::<Vec<_>>();
    entries.sort();
    for path in entries {
        if path.is_dir() {
            collect(&path, paths);
        } else if path.is_file() {
            paths.push(path);
        }
    }
}
fn main() {
    let package = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").unwrap());
    let root = package.parent().unwrap().parent().unwrap();
    let mut paths = vec![];
    for file in [
        "Cargo.toml",
        "Cargo.lock",
        "rust-toolchain.toml",
        "crates/ken-syntax/grammars.lock.json",
    ] {
        paths.push(root.join(file));
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
        "ken-retrieval/vendor/ruff-python-parser",
    ] {
        let directory = root.join("crates").join(name);
        println!("cargo:rerun-if-changed={}", directory.display());
        paths.push(directory.join("Cargo.toml"));
        let build = directory.join("build.rs");
        if build.is_file() {
            paths.push(build);
        }
        collect(&directory.join("src"), &mut paths);
        collect(&directory.join("resources"), &mut paths);
    }
    let mut catalog_sources = Vec::new();
    for name in ["patterns", "modern_patterns"] {
        let directory = root.join("src/ken/structural").join(name);
        collect(&directory, &mut paths);
        if directory.is_dir() {
            let mut resources = fs::read_dir(&directory)
                .unwrap()
                .map(|e| e.unwrap().path())
                .filter(|p| p.extension().is_some_and(|e| e == "toml"))
                .collect::<Vec<_>>();
            resources.sort();
            for path in resources {
                catalog_sources.push((
                    format!("{name}/{}", path.file_name().unwrap().to_str().unwrap()),
                    path,
                ));
            }
        }
    }
    paths.sort();
    paths.dedup();
    let mut hash = Sha256::new();
    for path in paths {
        println!("cargo:rerun-if-changed={}", path.display());
        let bytes = fs::read(&path).unwrap();
        for bytes in [
            path.strip_prefix(root)
                .unwrap()
                .to_str()
                .unwrap()
                .as_bytes(),
            bytes.as_slice(),
        ] {
            hash.update((bytes.len() as u64).to_be_bytes());
            hash.update(bytes);
        }
    }
    let identity = format!("{:x}", hash.finalize());
    let out = PathBuf::from(env::var_os("OUT_DIR").unwrap());
    fs::write(
        out.join("identity.rs"),
        format!("pub const IMPLEMENTATION_FINGERPRINT: &str = {identity:?};\n"),
    )
    .unwrap();
    let mut catalog = String::from("pub const SOURCES:&[CatalogSource]=&[\n");
    for (name, path) in catalog_sources {
        catalog.push_str(&format!(
            "CatalogSource{{path:{name:?},text:include_str!({:?})}},\n",
            path.to_str().unwrap()
        ));
    }
    catalog.push_str("];\n");
    fs::write(out.join("catalog_sources.rs"), catalog).unwrap();
    // The regression runs this exact program over isolated input trees, without Cargo.
    fs::write(
        out.join("identity-program"),
        env::current_exe().unwrap().to_str().unwrap(),
    )
    .unwrap();
}
