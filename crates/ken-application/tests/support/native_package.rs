//! Deliberately unqualified native package fixtures, not runtime acceptance proof.
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
};
pub fn bundle(directory: &Path, executable: &Path, grammar_manifest: Option<&Path>) -> String {
    std::fs::create_dir_all(directory.join("resources/inputs/grammars")).unwrap();
    for name in ["ken", "ken-rs", "ken-check-worker", "git"] {
        std::fs::copy(executable, directory.join(name)).unwrap();
        std::fs::set_permissions(directory.join(name), std::fs::Permissions::from_mode(0o555))
            .unwrap();
    }
    let grammar = directory.join("resources/inputs/grammars/manifest.json");
    if let Some(source) = grammar_manifest {
        let value: Value = serde_json::from_slice(&std::fs::read(source).unwrap()).unwrap();
        std::fs::copy(source, &grammar).unwrap();
        for row in value["libraries"].as_array().unwrap() {
            let name = row["file"].as_str().unwrap();
            std::fs::copy(
                source.parent().unwrap().join(name),
                grammar.parent().unwrap().join(name),
            )
            .unwrap();
        }
    } else {
        std::fs::write(&grammar, b"{}\n").unwrap();
    }
    std::fs::write(
        directory.join("resources/static.npz"),
        b"fixture; not a model",
    )
    .unwrap();
    std::fs::write(directory.join("resources/search.json"),json!({"format":"ken-search-installation/1","grammar_manifest":"inputs/grammars/manifest.json","ranking_directory":"inputs/ranking","private_parent":"../../../var/private","cache_parent":"../../../var/cache","bundled_npz":"static.npz","sources":{},"acquisition":"offline","legacy_runtime":{},"onnx_library":null,"translation":null}).to_string()).unwrap();
    let mut files = BTreeMap::new();
    fn visit(base: &Path, path: &Path, files: &mut BTreeMap<String, Value>) {
        let mut entries = std::fs::read_dir(path)
            .unwrap()
            .map(|entry| entry.unwrap().path())
            .collect::<Vec<PathBuf>>();
        entries.sort();
        for path in entries {
            if path.is_dir() {
                visit(base, &path, files);
            } else {
                let bytes = std::fs::read(&path).unwrap();
                let name = path
                    .strip_prefix(base)
                    .unwrap()
                    .to_str()
                    .unwrap()
                    .replace('\\', "/");
                let mode = if ["ken", "ken-rs", "ken-check-worker", "git"].contains(&name.as_str())
                {
                    0o555
                } else {
                    0o444
                };
                std::fs::set_permissions(&path, std::fs::Permissions::from_mode(mode)).unwrap();
                files.insert(name,json!({"sha256":format!("{:x}",Sha256::digest(&bytes)),"bytes":bytes.len(),"mode":mode}));
            }
        }
    }
    visit(directory, directory, &mut files);
    let manifest = json!({"format":"ken-native-package/1","target":{"os":"linux","arch":"x86_64","device":"cpu"},"entrypoints":{"launcher":"ken","cli":"ken-rs","check_worker":"ken-check-worker","git":"git"},"resources":"resources/search.json","files":files,"provenance":{"source":{"commit":"0000000000000000000000000000000000000000","dirty":false},"build":{"profile":"contract-fixture","rustc":"fixture"},"runtime":{"baseline":"fixture-host","system_libraries":[]},"qualification":{"accepted":false,"scope":"contract-fixture"}}});
    let bytes = serde_json::to_vec_pretty(&manifest).unwrap();
    std::fs::write(directory.join("FILES.json"), &bytes).unwrap();
    std::fs::set_permissions(
        directory.join("FILES.json"),
        std::fs::Permissions::from_mode(0o444),
    )
    .unwrap();
    format!("{:x}", Sha256::digest(bytes))
}
// Some integration targets import only bundle() from this shared fixture module.
#[allow(dead_code)]
pub fn replace(directory: &Path, name: &str, bytes: &[u8], mode: u32) -> String {
    std::fs::set_permissions(directory.join(name), std::fs::Permissions::from_mode(0o644)).unwrap();
    std::fs::write(directory.join(name), bytes).unwrap();
    std::fs::set_permissions(directory.join(name), std::fs::Permissions::from_mode(mode)).unwrap();
    let path = directory.join("FILES.json");
    let mut value: Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    value["files"][name] =
        json!({"bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(bytes)),"mode":mode});
    let raw = serde_json::to_vec_pretty(&value).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
    std::fs::write(&path, &raw).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o444)).unwrap();
    format!("{:x}", Sha256::digest(raw))
}
