//! Traverse real projects through the public source boundary.
use ken_core::{
    project::{DiscoveryContext, ProjectPaths},
    source_walk::{ProjectSources, SourceEntry},
};
use serde_json::Value;
use std::{
    fs,
    path::{Path, PathBuf},
};

fn sources(root: &Path) -> ProjectSources {
    let context = DiscoveryContext {
        cwd: root.into(),
        forced_root: None,
        home: Some(root.into()),
    };
    ProjectSources::new(ProjectPaths::at(root, &context).unwrap(), context)
}
fn file(root: &Path, name: &str, bytes: &[u8]) {
    let path = root.join(name);
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, bytes).unwrap();
}
fn populate(root: &Path, definition: &Value) {
    for field in ["files", "byte_files"] {
        if let Some(files) = definition[field].as_object() {
            for (name, value) in files {
                let text = value.as_str().unwrap();
                let bytes = if field == "files" {
                    text.as_bytes().to_vec()
                } else {
                    (0..text.len())
                        .step_by(2)
                        .map(|i| u8::from_str_radix(&text[i..i + 2], 16).unwrap())
                        .collect()
                };
                file(root, name, &bytes);
            }
        }
    }
    #[cfg(unix)]
    if let Some(links) = definition["links"].as_object() {
        for (name, target) in links {
            std::os::unix::fs::symlink(target.as_str().unwrap(), root.join(name)).unwrap();
        }
    }
}
fn ordered(owner: &ProjectSources, scope: &str) -> Vec<SourceEntry> {
    owner
        .walk(Path::new(scope))
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap()
}

#[test]
fn all_original_ordered_entries_scopes_unicode_and_internal_aliases_match() {
    let original: Value =
        serde_json::from_str(include_str!("fixtures/source-discovery/reference.json")).unwrap();
    let mut count = 0;
    for (definition, expected) in original["definitions"]
        .as_array()
        .unwrap()
        .iter()
        .zip(original["cases"].as_array().unwrap())
    {
        let temp = tempfile::tempdir().unwrap();
        populate(temp.path(), definition);
        let owner = sources(temp.path());
        for walk in expected["walks"].as_array().unwrap() {
            let scope = walk["scope"].as_str().unwrap();
            if walk.get("error").is_some() {
                assert!(
                    owner
                        .walk(Path::new(scope))
                        .err()
                        .unwrap()
                        .to_string()
                        .contains("escapes project root")
                );
            } else {
                let actual = ordered(&owner, scope);
                let entries: Vec<_> = actual
                    .iter()
                    .map(|e| serde_json::json!({"path":e.path.to_str().unwrap(),"is_dir":e.is_dir}))
                    .collect();
                assert_eq!(
                    Value::from(entries),
                    walk["entries"],
                    "case={} scope={scope}",
                    definition["id"]
                );
                let files: Vec<_> = actual
                    .iter()
                    .filter(|e| !e.is_dir)
                    .map(|e| e.path.to_str().unwrap())
                    .collect();
                assert_eq!(serde_json::json!(files), walk["files"]);
            }
            count += 1;
        }
    }
    assert_eq!(count, 51);
}

#[test]
fn a_new_walk_reads_new_rules_without_sharing_stale_filter_state() {
    let temp = tempfile::tempdir().unwrap();
    file(temp.path(), "main.py", b"");
    let owner = sources(temp.path());
    assert_eq!(ordered(&owner, ".")[0].path, PathBuf::from("main.py"));
    file(temp.path(), ".gitignore", b"*.py\n");
    assert_eq!(
        ordered(&owner, ".")
            .iter()
            .map(|e| e.path.clone())
            .collect::<Vec<_>>(),
        vec![PathBuf::from(".gitignore")]
    );
    file(temp.path(), ".gitignore", b"*.py\n!main.py\n");
    assert!(
        ordered(&owner, ".")
            .iter()
            .any(|e| e.path == Path::new("main.py"))
    );
}

#[cfg(unix)]
#[test]
fn external_file_directory_and_ancestor_cycle_are_errors_and_do_not_hide_valid_entries() {
    use std::os::unix::fs::symlink;
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("project");
    file(&root, "valid.py", b"valid");
    file(temp.path(), "outside/secret.py", b"private");
    symlink(temp.path().join("outside"), root.join("external-dir")).unwrap();
    symlink(
        temp.path().join("outside/secret.py"),
        root.join("external-file"),
    )
    .unwrap();
    symlink(".", root.join("cycle")).unwrap();
    let owner = sources(&root);
    let mut entries = vec![];
    let mut errors = vec![];
    for item in owner.walk(Path::new(".")).unwrap().take(20) {
        match item {
            Ok(entry) => entries.push(entry.path),
            Err(error) => errors.push(error.to_string()),
        }
    }
    assert_eq!(entries, vec![PathBuf::from("valid.py")]);
    assert_eq!(errors.len(), 3);
    assert!(errors.iter().any(|s| s.contains("cycle")));
    assert_eq!(
        errors
            .iter()
            .filter(|s| s.contains("escapes project root"))
            .count(),
        2
    );
    assert_eq!(
        fs::read(temp.path().join("outside/secret.py")).unwrap(),
        b"private"
    );
}

#[cfg(unix)]
fn permission_fixture() {
    use std::os::unix::fs::PermissionsExt;
    assert_ne!(
        unsafe { libc::geteuid() },
        0,
        "permission fixture requires a real ordinary user"
    );
    let temp = tempfile::tempdir().unwrap();
    for name in [
        "blocked/secret.py",
        "ignored/secret.py",
        "sibling/secret.py",
        "pkg/src/keep.py",
    ] {
        file(temp.path(), name, b"");
    }
    file(temp.path(), ".gitignore", b"ignored/\n");
    for name in ["blocked", "ignored", "sibling"] {
        fs::set_permissions(temp.path().join(name), fs::Permissions::from_mode(0)).unwrap();
    }
    let owner = sources(temp.path());
    let scoped = ordered(&owner, "pkg/src");
    assert_eq!(
        scoped.iter().map(|e| e.path.clone()).collect::<Vec<_>>(),
        vec![PathBuf::from("pkg/src/keep.py")]
    );
    fs::set_permissions(
        temp.path().join("sibling"),
        fs::Permissions::from_mode(0o700),
    )
    .unwrap();
    let errors: Vec<_> = owner
        .walk(Path::new("."))
        .unwrap()
        .filter_map(Result::err)
        .map(|e| e.to_string())
        .collect();
    for name in ["blocked", "ignored"] {
        fs::set_permissions(temp.path().join(name), fs::Permissions::from_mode(0o700)).unwrap();
    }
    assert_eq!(errors.len(), 1, "{errors:?}");
    assert!(errors[0].contains("blocked"));
}

#[cfg(unix)]
#[test]
fn unreadable_directory_is_an_error_but_ignored_directory_is_pruned() {
    use std::os::unix::{fs::PermissionsExt, process::CommandExt};
    if unsafe { libc::geteuid() } == 0 {
        let temp = tempfile::tempdir().unwrap();
        fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o755)).unwrap();
        let binary = temp.path().join("ordinary-user-source-test");
        fs::copy(std::env::current_exe().unwrap(), &binary).unwrap();
        fs::set_permissions(&binary, fs::Permissions::from_mode(0o755)).unwrap();
        let output = std::process::Command::new(binary)
            .uid(65534)
            .gid(65534)
            .args([
                "unreadable_directory_is_an_error_but_ignored_directory_is_pruned",
                "--exact",
                "--nocapture",
            ])
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "ordinary-user fixture failed: {}{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        return;
    }
    permission_fixture();
}
