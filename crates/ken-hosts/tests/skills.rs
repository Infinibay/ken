use ken_hosts::{Bundles, HostSelection, catalog, skills};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
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
fn bundles(value: &Value) -> Bundles {
    value
        .as_object()
        .unwrap()
        .iter()
        .map(|(name, files)| {
            (
                name.clone(),
                files
                    .as_object()
                    .unwrap()
                    .iter()
                    .map(|(path, data)| (path.clone(), hex(data.as_str().unwrap())))
                    .collect(),
            )
        })
        .collect()
}
fn snapshot(root: &Path) -> Value {
    fn walk(root: &Path, dir: &Path, out: &mut BTreeMap<String, Value>) {
        for entry in std::fs::read_dir(dir).unwrap() {
            let entry = entry.unwrap();
            let path = entry.path();
            if path.is_symlink() {
                continue;
            }
            if path.is_dir() {
                walk(root, &path, out);
            } else {
                let rel = path
                    .strip_prefix(root)
                    .unwrap()
                    .to_string_lossy()
                    .replace('\\', "/");
                let bytes = std::fs::read(path).unwrap();
                let value = if [".ken/installed-skills.json", ".ken/instructions.json"]
                    .contains(&rel.as_str())
                {
                    json!({"json":serde_json::from_slice::<Value>(&bytes).unwrap()})
                } else {
                    json!({"hex":bytes.iter().map(|b|format!("{b:02x}")).collect::<String>()})
                };
                out.insert(rel, value);
            }
        }
    }
    let mut out = BTreeMap::new();
    walk(root, root, &mut out);
    json!(out)
}
#[test]
fn embedded_complete_bundles_match_original_resource_owner_hashes() {
    let resources = catalog::bundled_skills().unwrap();
    assert_eq!(resources.len(), 8);
    let actual = resources
        .iter()
        .map(|(name, files)| {
            (
                name.clone(),
                files
                    .iter()
                    .map(|(path, bytes)| (path.clone(), format!("{:x}", Sha256::digest(bytes))))
                    .collect::<BTreeMap<_, _>>(),
            )
        })
        .collect::<BTreeMap<_, _>>();
    assert_eq!(json!(actual), fixture()["catalog"]);
    for name in [
        "ken-find-code-patterns",
        "ken-investigate-bug",
        "ken-prevent-regressions",
    ] {
        assert!(resources[name].contains_key("references/kql2/README.md"));
    }
    assert!(!resources["ken-locate-code"].contains_key("references/kql2/README.md"));
}
#[test]
fn original_owned_skill_install_update_edit_and_uninstall_lifecycle_matches() {
    let d = tempfile::tempdir().unwrap();
    let f = fixture();
    for event in f["skills"]["events"].as_array().unwrap() {
        if event["action"] == "edit" {
            std::fs::write(
                d.path().join(".agents/skills/ken-proof/SKILL.md"),
                "Local customization\n",
            )
            .unwrap();
        }
        let changes = if event["action"] == "uninstall" {
            skills::uninstall(d.path()).unwrap()
        } else {
            skills::install(
                d.path(),
                HostSelection {
                    codex: true,
                    ..Default::default()
                },
                &bundles(&event["bundles"]),
            )
            .unwrap()
        };
        assert_eq!(serde_json::to_value(changes).unwrap(), event["changes"]);
        assert_eq!(snapshot(d.path()), event["files"]);
    }
}
#[test]
fn unowned_identical_bundle_is_not_adopted_and_user_extras_survive() {
    let d = tempfile::tempdir().unwrap();
    let all = bundles(&fixture()["skills"]["initial"]);
    let unowned = d.path().join(".agents/skills/ken-example/SKILL.md");
    std::fs::create_dir_all(unowned.parent().unwrap()).unwrap();
    std::fs::write(&unowned, &all["ken-example"]["SKILL.md"]).unwrap();
    let changes = skills::install(
        d.path(),
        HostSelection {
            codex: true,
            ..Default::default()
        },
        &all,
    )
    .unwrap();
    assert!(changes.preserved.contains_key(".agents/skills/ken-example"));
    let note = d.path().join(".agents/skills/ken-proof/my-notes.txt");
    std::fs::write(&note, "Keep").unwrap();
    skills::uninstall(d.path()).unwrap();
    assert!(unowned.is_file());
    assert_eq!(std::fs::read_to_string(note).unwrap(), "Keep");
    assert!(!d.path().join(".agents/skills/ken-proof/SKILL.md").exists());
}
#[cfg(unix)]
#[test]
fn skill_symlinks_and_forged_manifest_targets_cannot_modify_external_files() {
    let all = bundles(&fixture()["skills"]["initial"]);
    for relative in [".agents", ".agents/skills", ".agents/skills/ken-example"] {
        let d = tempfile::tempdir().unwrap();
        let outside = tempfile::tempdir().unwrap();
        let path = d.path().join(relative);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::os::unix::fs::symlink(outside.path(), path).unwrap();
        let result = skills::install(
            d.path(),
            HostSelection {
                codex: true,
                ..Default::default()
            },
            &all,
        )
        .unwrap();
        assert!(!result.preserved.is_empty());
        assert_eq!(std::fs::read_dir(outside.path()).unwrap().count(), 0);
    }
    let d = tempfile::tempdir().unwrap();
    std::fs::create_dir(d.path().join(".ken")).unwrap();
    std::fs::write(
        d.path().join(".ken/installed-skills.json"),
        json!({"version":1,"skills":{"../../outside":{"SKILL.md":"a".repeat(64)}}}).to_string(),
    )
    .unwrap();
    assert!(skills::uninstall(d.path()).is_err());
}
