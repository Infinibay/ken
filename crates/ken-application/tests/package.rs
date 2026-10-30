#[path = "support/native_package.rs"]
mod support;
use ken_application::package::PackageApplication;
use std::{os::unix::fs::PermissionsExt, path::Path};
fn source(directory: &Path) -> String {
    support::bundle(directory, Path::new("/bin/true"), None)
}
#[test]
fn authenticated_install_preserves_foreign_files_and_rollback_reauthenticates_prior_release() {
    let temp = tempfile::tempdir().unwrap();
    let first = temp.path().join("first");
    let first_digest = source(&first);
    let prefix = temp.path().join("owned-prefix");
    std::fs::create_dir(&prefix).unwrap();
    std::fs::write(prefix.join("foreign"), "keep").unwrap();
    let app = PackageApplication::new(&prefix).unwrap();
    let first_info = app.authenticate(&first).unwrap();
    assert_eq!(first_info.manifest_sha256, first_digest);
    let installed = app.install(&first, &first_digest).unwrap();
    assert_eq!(installed.current_release, first_digest);
    assert!(installed.executable.is_absolute());
    assert_eq!(installed.executable, prefix.join("current/ken"));
    assert_eq!(
        installed.resources,
        prefix.join("current/resources/search.json")
    );
    assert_eq!(
        std::fs::read_to_string(prefix.join("foreign")).unwrap(),
        "keep"
    );
    let second = temp.path().join("second");
    let second_digest = source(&second);
    assert_eq!(first_digest, second_digest);
    let again = app.install(&second, &second_digest).unwrap();
    assert_eq!(again.current_release, first_digest);
    assert!(again.previous_release.is_none());
    std::fs::set_permissions(
        second.join("resources/static.npz"),
        std::fs::Permissions::from_mode(0o644),
    )
    .unwrap();
    std::fs::write(second.join("resources/static.npz"), "another fixture").unwrap();
    let mut manifest: serde_json::Value =
        serde_json::from_slice(&std::fs::read(second.join("FILES.json")).unwrap()).unwrap();
    let bytes = std::fs::read(second.join("resources/static.npz")).unwrap();
    use sha2::{Digest, Sha256};
    manifest["files"]["resources/static.npz"]["bytes"] = bytes.len().into();
    manifest["files"]["resources/static.npz"]["sha256"] =
        format!("{:x}", Sha256::digest(bytes)).into();
    std::fs::set_permissions(
        second.join("resources/static.npz"),
        std::fs::Permissions::from_mode(0o444),
    )
    .unwrap();
    std::fs::set_permissions(
        second.join("FILES.json"),
        std::fs::Permissions::from_mode(0o644),
    )
    .unwrap();
    let bytes = serde_json::to_vec_pretty(&manifest).unwrap();
    std::fs::write(second.join("FILES.json"), &bytes).unwrap();
    std::fs::set_permissions(
        second.join("FILES.json"),
        std::fs::Permissions::from_mode(0o444),
    )
    .unwrap();
    let digest = format!("{:x}", Sha256::digest(bytes));
    let installed = app.install(&second, &digest).unwrap();
    assert_eq!(
        installed.previous_release.as_deref(),
        Some(first_digest.as_str())
    );
    let rolled = app.rollback().unwrap();
    assert_eq!(rolled.current_release, first_digest);
    assert_eq!(rolled.previous_release.as_deref(), Some(digest.as_str()));
    assert_eq!(
        app.status().unwrap().current_release.as_deref(),
        Some(first_digest.as_str())
    );
    assert_eq!(
        std::fs::read_to_string(prefix.join("foreign")).unwrap(),
        "keep"
    );
}
#[test]
fn foreign_prefix_links_and_metadata_are_never_adopted_or_overwritten() {
    for collision in ["current", "previous", "bin/ken", ".ken-package"] {
        let temp = tempfile::tempdir().unwrap();
        let bundle = temp.path().join("bundle");
        let digest = source(&bundle);
        let prefix = temp.path().join("prefix");
        let target = prefix.join(collision);
        std::fs::create_dir_all(target.parent().unwrap()).unwrap();
        std::fs::write(&target, "user-owned").unwrap();
        let result = PackageApplication::new(&prefix).and_then(|app| app.install(&bundle, &digest));
        assert!(result.is_err(), "adopted {collision}");
        assert_eq!(std::fs::read_to_string(target).unwrap(), "user-owned");
    }
}
#[test]
fn manifest_digest_modes_traversal_symlinks_and_foreign_members_fail_before_activation() {
    let temp = tempfile::tempdir().unwrap();
    let bundle = temp.path().join("bundle");
    let digest = source(&bundle);
    let prefix = temp.path().join("prefix");
    let app = PackageApplication::new(&prefix).unwrap();
    assert!(app.install(&bundle, &"0".repeat(64)).is_err());
    assert!(app.status().unwrap().current_release.is_none());
    std::os::unix::fs::symlink("/etc/passwd", bundle.join("foreign-link")).unwrap();
    assert!(app.authenticate(&bundle).is_err());
    std::fs::remove_file(bundle.join("foreign-link")).unwrap();
    std::fs::write(bundle.join("undeclared"), "foreign").unwrap();
    assert!(app.authenticate(&bundle).is_err());
    std::fs::remove_file(bundle.join("undeclared")).unwrap();
    std::fs::set_permissions(
        bundle.join("ken-rs"),
        std::fs::Permissions::from_mode(0o4755),
    )
    .unwrap();
    assert!(app.install(&bundle, &digest).is_err());
    assert!(!prefix.join("current").exists());
}
#[test]
fn release_tampering_blocks_rollback_and_does_not_change_active_identity() {
    let temp = tempfile::tempdir().unwrap();
    let source_dir = temp.path().join("bundle");
    let digest = source(&source_dir);
    let prefix = temp.path().join("prefix");
    let app = PackageApplication::new(&prefix).unwrap();
    let installed = app.install(&source_dir, &digest).unwrap();
    let next = temp.path().join("next");
    source(&next);
    let next_digest = support::replace(&next, "resources/static.npz", b"next fixture", 0o444);
    let current = app.install(&next, &next_digest).unwrap();
    std::fs::set_permissions(
        installed.release_root.join("ken-rs"),
        std::fs::Permissions::from_mode(0o755),
    )
    .unwrap();
    std::fs::write(installed.release_root.join("ken-rs"), "tampered").unwrap();
    assert_eq!(
        std::fs::read(source_dir.join("ken-rs")).unwrap(),
        std::fs::read("/bin/true").unwrap(),
        "release must not share source inode"
    );
    assert!(app.authenticate(&installed.release_root).is_err());
    assert!(app.install(&source_dir, &digest).is_err());
    assert!(app.rollback().is_err());
    assert_eq!(
        prefix.join("current").canonicalize().unwrap(),
        current.release_root
    );
}

#[test]
fn installed_cache_paths_are_outside_authenticated_release_and_runtime_writes_do_not_break_reauthentication()
 {
    let temp = tempfile::tempdir().unwrap();
    let source_dir = temp.path().join("bundle");
    let digest = source(&source_dir);
    let prefix = temp.path().join("prefix");
    let app = PackageApplication::new(&prefix).unwrap();
    let report = app.install(&source_dir, &digest).unwrap();
    let resources: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&report.resources).unwrap()).unwrap();
    for field in ["cache_parent", "private_parent"] {
        let path = report
            .resources
            .parent()
            .unwrap()
            .join(resources[field].as_str().unwrap());
        std::fs::create_dir_all(&path).unwrap();
        let path = path.canonicalize().unwrap();
        assert!(!path.starts_with(&report.release_root));
        assert!(path.starts_with(prefix.canonicalize().unwrap()));
        std::fs::write(path.join("runtime-cache"), "generated").unwrap();
    }
    assert_eq!(
        app.authenticate(&report.release_root)
            .unwrap()
            .manifest_sha256,
        digest
    );
}
#[test]
fn interrupted_owned_staging_is_recovered_but_foreign_staging_names_are_preserved() {
    let temp = tempfile::tempdir().unwrap();
    let source_dir = temp.path().join("bundle");
    let digest = source(&source_dir);
    let prefix = temp.path().join("prefix");
    let app = PackageApplication::new(&prefix).unwrap();
    let installed = app.install(&source_dir, &digest).unwrap();
    let foreign = prefix.join(".unowned-stage");
    std::fs::create_dir(&foreign).unwrap();
    std::fs::write(foreign.join("keep"), "unowned").unwrap();
    drop(app);
    let reopened = PackageApplication::new(&prefix).unwrap();
    assert_eq!(
        reopened.status().unwrap().current_release.as_deref(),
        Some(digest.as_str())
    );
    assert_eq!(
        reopened
            .authenticate(&installed.release_root)
            .unwrap()
            .manifest_sha256,
        digest
    );
    assert_eq!(
        std::fs::read_to_string(foreign.join("keep")).unwrap(),
        "unowned"
    );
}
#[test]
fn real_kill_at_install_boundaries_recovers_only_owned_work_and_never_half_activates() {
    use std::{
        io::{BufRead, BufReader},
        os::unix::process::ExitStatusExt,
        process::{Command, Stdio},
    };
    for phase in [
        "staging_copied",
        "release_published",
        "activation_prepared",
        "activated",
    ] {
        let temp = tempfile::tempdir().unwrap();
        let first = temp.path().join("first");
        let first_sha = source(&first);
        let prefix = temp.path().join("prefix");
        PackageApplication::new(&prefix)
            .unwrap()
            .install(&first, &first_sha)
            .unwrap();
        let next = temp.path().join("next");
        source(&next);
        let next_sha = support::replace(&next, "resources/static.npz", b"next fixture", 0o444);
        let foreign = prefix.join(".foreign-stage");
        std::fs::create_dir(&foreign).unwrap();
        std::fs::write(foreign.join("keep"), "foreign").unwrap();
        let mut child = Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "package_process", "--ignored", "--nocapture"])
            .env("PACKAGE_TEST_PREFIX", &prefix)
            .env("PACKAGE_TEST_BUNDLE", &next)
            .env("PACKAGE_TEST_DIGEST", &next_sha)
            .env("PACKAGE_TEST_PHASE", phase)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .unwrap();
        let mut stdout = BufReader::new(child.stdout.take().unwrap());
        loop {
            let mut line = String::new();
            assert!(
                stdout.read_line(&mut line).unwrap() > 0,
                "child ended before {phase}"
            );
            if line.contains("package-event:") {
                assert!(line.contains(phase));
                break;
            }
        }
        child.kill().unwrap();
        assert_eq!(child.wait().unwrap().signal(), Some(9));
        let app = PackageApplication::new(&prefix).unwrap();
        let status = app.status().unwrap();
        let expected = if phase == "activated" {
            &next_sha
        } else {
            &first_sha
        };
        assert_eq!(status.current_release.as_deref(), Some(expected.as_str()));
        assert_eq!(
            std::fs::read_to_string(foreign.join("keep")).unwrap(),
            "foreign"
        );
        assert_eq!(
            app.authenticate(&prefix.join("releases").join(expected))
                .unwrap()
                .manifest_sha256,
            *expected
        );
        assert_eq!(
            app.status().unwrap().current_release,
            status.current_release
        );
    }
}
#[test]
#[ignore = "native install fault harness selected explicitly by actual SIGKILL tests"]
fn package_process() {
    use std::io::Write;
    let prefix = std::env::var_os("PACKAGE_TEST_PREFIX").unwrap();
    let bundle = std::env::var_os("PACKAGE_TEST_BUNDLE").unwrap();
    let digest = std::env::var("PACKAGE_TEST_DIGEST").unwrap();
    let phase = std::env::var("PACKAGE_TEST_PHASE").unwrap();
    let app = PackageApplication::new(Path::new(&prefix)).unwrap();
    app.install_with_progress(Path::new(&bundle), &digest, &mut |event| {
        let value = serde_json::to_value(event).unwrap();
        if value["phase"] == phase {
            println!("package-event:{value}");
            std::io::stdout().flush().unwrap();
            let mut line = String::new();
            assert!(std::io::stdin().read_line(&mut line).unwrap() > 0);
        }
    })
    .unwrap();
}
#[test]
fn native_git_selection_requires_absolute_override_and_never_project_path_search() {
    use ken_core::native_program::git_program_from;
    let temp = tempfile::tempdir().unwrap();
    let release = temp.path().join("release");
    std::fs::create_dir(&release).unwrap();
    let git = release.join("git");
    std::fs::copy("/bin/true", &git).unwrap();
    assert_eq!(
        git_program_from(None, &release.join("ken-rs")).unwrap(),
        git
    );
    assert!(
        git_program_from(
            Some(std::ffi::OsStr::new("relative/git")),
            &release.join("ken-rs")
        )
        .is_err()
    );
    let explicit = Path::new("/bin/true");
    assert_eq!(
        git_program_from(Some(explicit.as_os_str()), &release.join("ken-rs")).unwrap(),
        explicit
    );
    std::fs::remove_file(&git).unwrap();
    assert!(git_program_from(None, &release.join("ken-rs")).is_err());
}
#[test]
fn manifest_rejects_traversal_foreign_targets_and_writable_release_state() {
    let temp = tempfile::tempdir().unwrap();
    let bundle = temp.path().join("bundle");
    source(&bundle);
    let app = PackageApplication::new(&temp.path().join("prefix")).unwrap();
    let original = std::fs::read(bundle.join("FILES.json")).unwrap();
    for kind in ["traversal", "target", "state"] {
        let mut value: serde_json::Value = serde_json::from_slice(&original).unwrap();
        if kind == "traversal" {
            let entry = value["files"]["ken-rs"].clone();
            value["files"]["../foreign"] = entry;
        } else if kind == "target" {
            value["target"]["arch"] = "aarch64".into();
        } else {
            let path = bundle.join("resources/search.json");
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
            let mut resource: serde_json::Value =
                serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
            resource["cache_parent"] = "mutable-in-release".into();
            std::fs::write(&path, resource.to_string()).unwrap();
            let bytes = std::fs::read(&path).unwrap();
            use sha2::{Digest, Sha256};
            value["files"]["resources/search.json"]["bytes"] = bytes.len().into();
            value["files"]["resources/search.json"]["sha256"] =
                format!("{:x}", Sha256::digest(bytes)).into();
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o444)).unwrap();
        }
        std::fs::set_permissions(
            bundle.join("FILES.json"),
            std::fs::Permissions::from_mode(0o644),
        )
        .unwrap();
        std::fs::write(
            bundle.join("FILES.json"),
            serde_json::to_vec(&value).unwrap(),
        )
        .unwrap();
        std::fs::set_permissions(
            bundle.join("FILES.json"),
            std::fs::Permissions::from_mode(0o444),
        )
        .unwrap();
        assert!(app.authenticate(&bundle).is_err(), "accepted {kind}");
    }
}
#[test]
fn declared_torch_runtime_is_validated_by_installation_owner_without_eager_model_loading() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("installation.json");
    std::fs::write(&path,serde_json::json!({"format":"ken-search-installation/1","grammar_manifest":"unprepared.json","ranking_directory":"unprepared-ranks","private_parent":"private","cache_parent":"cache","bundled_npz":"static.npz","sources":{},"acquisition":"offline","legacy_runtime":{},"onnx_library":null,"translation":null,"torch":{"registration":{"format":"invalid"},"module_path":"backend.so","core_root":"torch"}}).to_string()).unwrap();
    let error = ken_search::SearchInstallation::open_model_factory(&path)
        .err()
        .expect("declared malformed torch must not be silently ignored");
    assert!(
        error.to_string().contains("transformer")
            || error.to_string().contains("format")
            || error.to_string().contains("missing field")
    );
    assert!(!temp.path().join("private").exists());
}
