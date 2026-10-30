use ken_hosts::instructions;
use serde_json::{Value, json};
use std::{collections::BTreeMap, path::Path};
fn fixture() -> Value {
    serde_json::from_str(include_str!("fixtures/hosts-domain.json")).unwrap()
}
fn hex(s: &str) -> Vec<u8> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap())
        .collect()
}
fn snapshot(root: &Path) -> Value {
    fn walk(root: &Path, dir: &Path, out: &mut BTreeMap<String, Value>) {
        for entry in std::fs::read_dir(dir).unwrap() {
            let path = entry.unwrap().path();
            if path.is_dir() {
                walk(root, &path, out);
            } else {
                let rel = path
                    .strip_prefix(root)
                    .unwrap()
                    .to_string_lossy()
                    .replace('\\', "/");
                let bytes = std::fs::read(path).unwrap();
                out.insert(
                    rel.clone(),
                    if rel == ".ken/instructions.json" {
                        json!({"json":serde_json::from_slice::<Value>(&bytes).unwrap()})
                    } else {
                        json!({"hex":bytes.iter().map(|b|format!("{b:02x}")).collect::<String>()})
                    },
                );
            }
        }
    }
    let mut out = BTreeMap::new();
    walk(root, root, &mut out);
    json!(out)
}
#[test]
fn optional_owned_guidance_preserves_original_prefix_crlf_and_ownership_format() {
    let f = fixture();
    assert_eq!(instructions::guidance(), f["guidance"].as_str().unwrap());
    for case in f["instructions"].as_array().unwrap() {
        let d = tempfile::tempdir().unwrap();
        let initial = hex(case["initial"].as_str().unwrap());
        if !initial.is_empty() {
            std::fs::write(d.path().join("AGENTS.md"), initial).unwrap();
        }
        instructions::install(d.path(), Some(true), true).unwrap();
        assert_eq!(snapshot(d.path()), case["first"]);
        instructions::install(d.path(), Some(true), true).unwrap();
        assert_eq!(snapshot(d.path()), case["second"]);
        instructions::uninstall(d.path()).unwrap();
        assert_eq!(snapshot(d.path()), case["removed"]);
    }
}
#[test]
fn declined_unowned_or_modified_guidance_is_never_overwritten() {
    let d = tempfile::tempdir().unwrap();
    instructions::install(d.path(), None, false).unwrap();
    instructions::install(d.path(), Some(false), false).unwrap();
    assert!(!d.path().join("AGENTS.md").exists());
    instructions::install(d.path(), Some(true), false).unwrap();
    let path = d.path().join("AGENTS.md");
    let edited = std::fs::read_to_string(&path)
        .unwrap()
        .replace("English", "our language");
    std::fs::write(&path, &edited).unwrap();
    instructions::install(d.path(), Some(true), false).unwrap();
    instructions::uninstall(d.path()).unwrap();
    assert_eq!(std::fs::read_to_string(path).unwrap(), edited);
}
#[cfg(unix)]
#[test]
fn symlinked_guidance_and_incomplete_markers_are_preserved() {
    let d = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    let target = outside.path().join("notes.md");
    std::fs::write(&target, "Keep").unwrap();
    let path = d.path().join("AGENTS.md");
    std::os::unix::fs::symlink(&target, &path).unwrap();
    instructions::install(d.path(), Some(true), false).unwrap();
    assert_eq!(std::fs::read_to_string(&target).unwrap(), "Keep");
    std::fs::remove_file(&path).unwrap();
    let malformed = "User\n<!-- ken:instructions:start -->\nIncomplete";
    std::fs::write(&path, malformed).unwrap();
    instructions::install(d.path(), Some(true), false).unwrap();
    assert_eq!(std::fs::read_to_string(path).unwrap(), malformed);
}
