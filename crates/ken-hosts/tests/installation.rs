use ken_hosts::{Bundles, HostInstaller, HostSelection, InstallOptions, NativeCommand, jsonc};
use serde_json::{Value, json};
use std::{collections::BTreeMap, path::Path};
fn bundles() -> Bundles {
    BTreeMap::from([(
        "ken-example".into(),
        BTreeMap::from([("SKILL.md".into(), b"# Example\n".to_vec())]),
    )])
}
fn command() -> NativeCommand {
    NativeCommand::new(
        "/native/ken",
        vec!["--resources".into(), "/native/resources.json".into()],
    )
    .unwrap()
}
fn write(root: &Path, path: &str, text: &str) {
    let path = root.join(path);
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(path, text).unwrap();
}
fn snapshot(root: &Path) -> BTreeMap<String, Vec<u8>> {
    fn walk(root: &Path, dir: &Path, out: &mut BTreeMap<String, Vec<u8>>) {
        for entry in std::fs::read_dir(dir).unwrap() {
            let path = entry.unwrap().path();
            if path.is_symlink() {
                continue;
            }
            let relative = path
                .strip_prefix(root)
                .unwrap()
                .to_string_lossy()
                .replace('\\', "/");
            if relative == ".ken" {
                continue;
            }
            if path.is_dir() {
                walk(root, &path, out);
            } else {
                out.insert(relative, std::fs::read(path).unwrap());
            }
        }
    }
    let mut out = BTreeMap::new();
    walk(root, root, &mut out);
    out
}
#[test]
fn all_host_install_reinstall_and_uninstall_preserve_original_user_configs() {
    let d = tempfile::tempdir().unwrap();
    let root = d.path();
    write(
        root,
        ".claude/settings.json",
        r#"{"permissions":{"allow":["Bash(test *)"]},"hooks":{"Stop":[{"hooks":[{"type":"command","command":"echo user"}]}]}}"#,
    );
    write(
        root,
        ".mcp.json",
        r#"{"metadata":{"keep":true},"mcpServers":{"other":{"command":"other"}}}"#,
    );
    write(
        root,
        ".codex/config.toml",
        "model='custom'\n# User comment\n",
    );
    write(root, ".codex/hooks.json", r#"{"model":"custom"}"#);
    write(
        root,
        "opencode.jsonc",
        "// User comment\n{\"url\":\"https://example.com/a//b\",\"literal\":\",}\",\"mcp\":{\"other\":{\"type\":\"remote\",\"url\":\"https://other\"},},}\n",
    );
    write(
        root,
        ".dsh/ken.cordis.json",
        r#"[{"insert":[{"id":"other","name":"other-plugin"}]},{"id":"keep","disabled":true}]"#,
    );
    let before = snapshot(root);
    let installer = HostInstaller::new(root, command(), bundles()).unwrap();
    let options = InstallOptions {
        hosts: HostSelection {
            claude: true,
            codex: true,
            opencode: true,
            deepseek: true,
        },
        instructions: Some(true),
        ..Default::default()
    };
    installer.plan_install(&options).unwrap().apply().unwrap();
    let once = snapshot(root);
    let again = installer.plan_install(&options).unwrap();
    again.apply().unwrap();
    assert_eq!(snapshot(root), once);
    let claude: Value =
        serde_json::from_slice(&std::fs::read(root.join(".mcp.json")).unwrap()).unwrap();
    assert_eq!(claude["mcpServers"]["ken"]["command"], "/native/ken");
    assert_eq!(
        claude["mcpServers"]["ken"]["args"],
        json!(["--resources", "/native/resources.json", "mcp"])
    );
    let text = std::fs::read_to_string(root.join("opencode.jsonc")).unwrap();
    assert!(text.contains("// User comment"));
    assert_eq!(jsonc::parse(&text).unwrap()["literal"], ",}");
    let overlay: Value =
        serde_json::from_slice(&std::fs::read(root.join(".dsh/ken.cordis.json")).unwrap()).unwrap();
    assert!(overlay.to_string().contains("/native/ken"));
    assert!(!overlay.to_string().contains("python"));
    assert!(root.join(".agents/skills/ken-example/SKILL.md").is_file());
    assert!(root.join(".claude/skills/ken-example/SKILL.md").is_file());
    assert!(!root.join(".dsh/skills").exists());
    assert!(!root.join(".opencode/skills").exists());
    installer.plan_uninstall().unwrap().apply().unwrap();
    assert_eq!(snapshot(root), before);
}
#[test]
fn no_wire_skips_all_host_skills_and_instruction_mutations() {
    let d = tempfile::tempdir().unwrap();
    let installer = HostInstaller::new(d.path(), command(), bundles()).unwrap();
    installer
        .plan_install(&InstallOptions {
            no_wire: true,
            instructions: Some(true),
            ..Default::default()
        })
        .unwrap()
        .apply()
        .unwrap();
    assert_eq!(std::fs::read_dir(d.path()).unwrap().count(), 0);
}
#[test]
fn edited_or_unowned_host_entries_are_not_removed_or_adopted() {
    let d = tempfile::tempdir().unwrap();
    let installer = HostInstaller::new(d.path(), command(), bundles()).unwrap();
    let options = InstallOptions {
        hosts: HostSelection {
            codex: true,
            ..Default::default()
        },
        ..Default::default()
    };
    installer.plan_install(&options).unwrap().apply().unwrap();
    let path = d.path().join(".codex/config.toml");
    let edited = std::fs::read_to_string(&path).unwrap() + "# User-owned extension\n";
    std::fs::write(&path, &edited).unwrap();
    let report = installer.plan_uninstall().unwrap().apply().unwrap();
    assert_eq!(std::fs::read_to_string(path).unwrap(), edited);
    assert!(report.preserved.contains_key(".codex/config.toml"));
    let d = tempfile::tempdir().unwrap();
    let config = r#"{"mcpServers":{"ken":{"command":"/native/ken","args":["--resources","/native/resources.json","mcp"]}},"keep":1}"#;
    write(d.path(), ".mcp.json", config);
    let installer = HostInstaller::new(d.path(), command(), bundles()).unwrap();
    installer
        .plan_install(&InstallOptions {
            hosts: HostSelection {
                claude: true,
                ..Default::default()
            },
            ..Default::default()
        })
        .unwrap()
        .apply()
        .unwrap();
    installer.plan_uninstall().unwrap().apply().unwrap();
    assert_eq!(
        std::fs::read_to_string(d.path().join(".mcp.json")).unwrap(),
        config
    );
}
#[test]
fn stale_installation_plan_does_not_overwrite_changes_or_publish_other_host_files() {
    let d = tempfile::tempdir().unwrap();
    let installer = HostInstaller::new(d.path(), command(), bundles()).unwrap();
    let plan = installer
        .plan_install(&InstallOptions {
            hosts: HostSelection {
                codex: true,
                ..Default::default()
            },
            ..Default::default()
        })
        .unwrap();
    write(
        d.path(),
        ".codex/config.toml",
        "model='changed after plan'\n",
    );
    assert!(plan.apply().is_err());
    assert_eq!(
        std::fs::read_to_string(d.path().join(".codex/config.toml")).unwrap(),
        "model='changed after plan'\n"
    );
    assert!(!d.path().join(".codex/hooks.json").exists());
}
#[test]
fn malformed_or_ambiguous_host_config_is_preserved() {
    let d = tempfile::tempdir().unwrap();
    write(d.path(), ".claude/settings.json", "{broken");
    let installer = HostInstaller::new(d.path(), command(), bundles()).unwrap();
    assert!(
        installer
            .plan_install(&InstallOptions {
                hosts: HostSelection {
                    claude: true,
                    ..Default::default()
                },
                ..Default::default()
            })
            .is_err()
    );
    assert_eq!(
        std::fs::read_to_string(d.path().join(".claude/settings.json")).unwrap(),
        "{broken"
    );
    let d = tempfile::tempdir().unwrap();
    write(d.path(), "opencode.json", "{\"model\":\"a\"}");
    write(d.path(), "opencode.jsonc", "// Keep\n{\"model\":\"b\"}");
    let before = snapshot(d.path());
    let installer = HostInstaller::new(d.path(), command(), bundles()).unwrap();
    let report = installer
        .plan_install(&InstallOptions {
            hosts: HostSelection {
                opencode: true,
                ..Default::default()
            },
            ..Default::default()
        })
        .unwrap()
        .apply()
        .unwrap();
    assert_eq!(
        std::fs::read(d.path().join("opencode.json")).unwrap(),
        before["opencode.json"]
    );
    assert_eq!(
        std::fs::read(d.path().join("opencode.jsonc")).unwrap(),
        before["opencode.jsonc"]
    );
    assert!(!report.preserved.is_empty());
}
#[cfg(unix)]
#[test]
fn symlink_replacement_after_planning_and_corrupt_host_ownership_cannot_escape() {
    let d = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    let installer = HostInstaller::new(d.path(), command(), bundles()).unwrap();
    let plan = installer
        .plan_install(&InstallOptions {
            hosts: HostSelection {
                codex: true,
                ..Default::default()
            },
            ..Default::default()
        })
        .unwrap();
    std::os::unix::fs::symlink(outside.path(), d.path().join(".codex")).unwrap();
    assert!(plan.apply().is_err());
    assert_eq!(std::fs::read_dir(outside.path()).unwrap().count(), 0);
    let d = tempfile::tempdir().unwrap();
    write(
        d.path(),
        ".ken/installed-hosts.json",
        r#"{"version":1,"files":{"../../outside":{"sha256":"bad","before":null}}}"#,
    );
    let installer = HostInstaller::new(d.path(), command(), bundles()).unwrap();
    assert!(installer.plan_uninstall().is_err());
}

#[cfg(unix)]
#[test]
fn explicit_codex_force_repairs_owner_write_and_retains_invalid_bytes_for_rollback() {
    use std::os::unix::fs::PermissionsExt;
    let d = tempfile::tempdir().unwrap();
    write(d.path(), ".codex/hooks.json", "{broken user content");
    let directory = d.path().join(".codex");
    std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o500)).unwrap();
    struct Restore(std::path::PathBuf);
    impl Drop for Restore {
        fn drop(&mut self) {
            let _ = std::fs::set_permissions(&self.0, std::fs::Permissions::from_mode(0o700));
        }
    }
    let _restore = Restore(directory.clone());
    let installer = HostInstaller::new(d.path(), command(), bundles()).unwrap();
    let options = InstallOptions {
        hosts: HostSelection {
            codex: true,
            ..Default::default()
        },
        force_codex: true,
        ..Default::default()
    };
    installer.plan_install(&options).unwrap().apply().unwrap();
    assert_ne!(
        std::fs::metadata(&directory).unwrap().permissions().mode() & 0o200,
        0
    );
    assert_eq!(
        std::fs::read_to_string(directory.join("hooks.json.ken-backup")).unwrap(),
        "{broken user content"
    );
    assert!(
        serde_json::from_slice::<Value>(&std::fs::read(directory.join("hooks.json")).unwrap())
            .is_ok()
    );
    let installed = std::fs::read(directory.join("hooks.json")).unwrap();
    installer
        .plan_install(&InstallOptions {
            hosts: options.hosts,
            ..Default::default()
        })
        .unwrap()
        .apply()
        .unwrap();
    assert_eq!(
        std::fs::read(directory.join("hooks.json")).unwrap(),
        installed
    );
    installer.plan_uninstall().unwrap().apply().unwrap();
    assert_eq!(
        std::fs::read_to_string(directory.join("hooks.json")).unwrap(),
        "{broken user content"
    );
}
