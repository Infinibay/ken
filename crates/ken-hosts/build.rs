//! Embed the existing package resource tree without a Python build/runtime.
use std::{
    collections::BTreeSet,
    env, fs,
    path::{Path, PathBuf},
};
fn files(directory: &Path, prefix: &str, out: &mut Vec<(String, PathBuf)>) {
    println!("cargo:rerun-if-changed={}", directory.display());
    let mut entries = fs::read_dir(directory)
        .expect("resource directory")
        .map(|e| e.expect("resource entry"))
        .collect::<Vec<_>>();
    entries.sort_by_key(|e| e.file_name());
    for entry in entries {
        let name = entry.file_name().into_string().expect("UTF8 resource name");
        let path = entry.path();
        let kind = entry.file_type().expect("resource type");
        if kind.is_dir() {
            files(&path, &format!("{prefix}{name}/"), out);
        } else if kind.is_file() {
            out.push((format!("{prefix}{name}"), path));
        } else {
            panic!(
                "resource is not a regular file/directory: {}",
                path.display()
            );
        }
    }
}
fn main() {
    let manifest = PathBuf::from(env::var_os("CARGO_MANIFEST_DIR").expect("manifest directory"));
    let source = manifest.join("resources/skills");
    let mut folders = fs::read_dir(source.join("bundled"))
        .expect("bundled skills")
        .map(|e| e.expect("skill folder"))
        .collect::<Vec<_>>();
    folders.sort_by_key(|e| e.file_name());
    let mut code = String::from("pub const RESOURCES: &[(&str,&str,&[u8])] = &[\n");
    let mut count = 0;
    for folder in folders {
        if !folder.file_type().expect("skill type").is_dir() {
            continue;
        }
        let name = folder.file_name().into_string().expect("skill name");
        assert!(
            name.starts_with("ken-")
                && name[4..].split('-').all(|part| !part.is_empty()
                    && part
                        .bytes()
                        .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit())),
            "invalid bundled skill name"
        );
        let mut resources = Vec::new();
        files(&folder.path(), "", &mut resources);
        assert!(
            resources.iter().any(|(n, _)| n == "SKILL.md"),
            "missing SKILL.md"
        );
        if [
            "ken-find-code-patterns",
            "ken-investigate-bug",
            "ken-prevent-regressions",
        ]
        .contains(&name.as_str())
        {
            files(
                &source.join("references/kql2"),
                "references/kql2/",
                &mut resources,
            );
        }
        let mut seen = BTreeSet::new();
        for (relative, path) in resources {
            assert!(seen.insert(relative.clone()), "duplicate resource");
            let path = fs::canonicalize(path).expect("resource path");
            code.push_str(&format!(
                "({name:?},{relative:?},include_bytes!({:?})),\n",
                path.to_string_lossy()
            ));
        }
        count += 1;
    }
    assert!(count > 0, "no bundled skills");
    code.push_str("];\n");
    let instructions = manifest.join("resources/guidance.txt");
    println!("cargo:rerun-if-changed={}", instructions.display());
    println!(
        "cargo:rerun-if-changed={}",
        manifest.join("resources/provenance.json").display()
    );
    let guidance = fs::read_to_string(instructions).expect("authenticated native guidance");
    code.push_str(&format!("pub const GUIDANCE: &str = {guidance:?};\n"));
    fs::write(
        PathBuf::from(env::var_os("OUT_DIR").expect("build output")).join("resources.rs"),
        code,
    )
    .expect("embedded resources");
}
