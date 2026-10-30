#[path = "../../ken-application/tests/support/native_package.rs"]
mod support;
use clap::Parser;
use ken_cli::package::{PackageAction, PackageCommand};
use std::{
    path::Path,
    process::{Command, Output},
};
#[derive(Parser)]
struct Parse {
    #[command(subcommand)]
    command: PackageCommand,
}
fn call(root: &Path, args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_ken-rs"))
        .args(args)
        .env_clear()
        .env("HOME", root)
        .env("PATH", "")
        .current_dir(root)
        .output()
        .unwrap()
}
#[test]
fn package_cli_authenticates_installs_and_reports_owned_deployment_without_models() {
    let root = tempfile::tempdir().unwrap();
    let bundle = root.path().join("bundle");
    let digest = support::bundle(&bundle, Path::new("/bin/true"), None);
    let prefix = root.path().join("prefix");
    for args in [
        vec![
            "package",
            "authenticate",
            bundle.to_str().unwrap(),
            "--json",
        ],
        vec![
            "package",
            "install",
            bundle.to_str().unwrap(),
            "--manifest-sha256",
            &digest,
            "--prefix",
            prefix.to_str().unwrap(),
            "--json",
        ],
        vec![
            "package",
            "status",
            "--prefix",
            prefix.to_str().unwrap(),
            "--json",
        ],
    ] {
        let output = call(root.path(), &args);
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let value: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
        assert!(value.is_object());
    }
    assert!(prefix.join("current/ken").is_file());
    assert!(!prefix.join("var/cache").exists());
}
#[test]
fn package_cli_invalid_digest_and_unowned_links_fail_without_overwriting() {
    let root = tempfile::tempdir().unwrap();
    let bundle = root.path().join("bundle");
    let digest = support::bundle(&bundle, Path::new("/bin/true"), None);
    let prefix = root.path().join("prefix");
    std::fs::create_dir(&prefix).unwrap();
    std::fs::write(prefix.join("current"), "foreign").unwrap();
    for sha in ["f".repeat(64), digest] {
        let output = call(
            root.path(),
            &[
                "package",
                "install",
                bundle.to_str().unwrap(),
                "--manifest-sha256",
                &sha,
                "--prefix",
                prefix.to_str().unwrap(),
                "--json",
            ],
        );
        assert!(!output.status.success());
        assert_eq!(
            std::fs::read_to_string(prefix.join("current")).unwrap(),
            "foreign"
        );
    }
}
#[test]
fn package_cli_requires_explicit_source_identity_and_prefix() {
    assert!(Parse::try_parse_from(["ken-rs", "package", "install", "bundle"]).is_err());
    let parsed =
        Parse::try_parse_from(["ken-rs", "package", "rollback", "--prefix", "/owned"]).unwrap();
    assert!(matches!(
        parsed.command,
        PackageCommand::Package {
            command: PackageAction::Rollback { .. }
        }
    ));
}
#[test]
fn native_launcher_executes_only_sibling_backend_with_owned_loader_paths_and_stable_install_identity()
 {
    let root = tempfile::tempdir().unwrap();
    let release = root.path().join("releases/version");
    std::fs::create_dir_all(release.join("lib")).unwrap();
    std::fs::copy(env!("CARGO_BIN_EXE_ken"), release.join("ken")).unwrap();
    std::fs::copy(std::env::current_exe().unwrap(), release.join("ken-rs")).unwrap();
    std::fs::copy("/bin/true", release.join("git")).unwrap();
    std::os::unix::fs::symlink("releases/version", root.path().join("current")).unwrap();
    let output = Command::new(root.path().join("current/ken"))
        .args(["--exact", "package_backend", "--ignored", "--nocapture"])
        .env_clear()
        .env("PATH", "")
        .env("LD_LIBRARY_PATH", "/unowned/developer/path")
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let text = String::from_utf8(output.stdout).unwrap();
    let row = text
        .lines()
        .find_map(|line| line.strip_prefix("launcher-observation:"))
        .unwrap();
    let value: serde_json::Value = serde_json::from_str(row).unwrap();
    assert_eq!(value["loader"], release.join("lib").to_str().unwrap());
    assert_eq!(
        value["install"],
        root.path().join("current/ken").to_str().unwrap()
    );
    assert_eq!(value["git"], release.join("git").to_str().unwrap());
    assert_eq!(
        value["resources"],
        root.path()
            .join("current/resources/search.json")
            .to_str()
            .unwrap()
    );
    assert!(!release.join("__pycache__").exists());
}
#[test]
#[ignore = "native launcher backend probe; selected explicitly by launcher test"]
fn package_backend() {
    println!(
        "launcher-observation:{}",
        serde_json::json!({"loader":std::env::var("LD_LIBRARY_PATH").unwrap(),"install":std::env::var("KEN_NATIVE_INSTALL_EXECUTABLE").unwrap(),"git":std::env::var("KEN_GIT_PROGRAM").unwrap(),"resources":std::env::var("KEN_NATIVE_INSTALL_RESOURCES").unwrap()})
    );
}
