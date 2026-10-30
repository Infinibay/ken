#[path = "../../ken-application/tests/support/native_package.rs"]
mod package_support;
use clap::Parser;
use ken_cli::installation::InstallationCommand;
use serde_json::{Value, json};
use std::{
    path::{Path, PathBuf},
    process::{Command, Output},
};
#[derive(Parser)]
struct ParserFixture {
    #[command(subcommand)]
    command: InstallationCommand,
}
fn args(values: &[&str]) -> InstallationCommand {
    ParserFixture::try_parse_from(std::iter::once("ken-rs").chain(values.iter().copied()))
        .unwrap()
        .command
}
fn run(root: &Path, resources: &Path, arguments: &[&str]) -> Output {
    let mut command = Command::new(env!("CARGO_BIN_EXE_ken-rs"));
    command
        .arg("--resources")
        .arg(resources)
        .args(arguments)
        .current_dir(root)
        .env_clear()
        .env("HOME", root)
        .env("PATH", "")
        .env("KEN_CONFIG_DIR", root.join(".fixture-config"));
    if let Some(blas) = std::env::var_os("KEN_DENSE_BLAS_DIR") {
        command.env("KEN_DENSE_BLAS_DIR", blas);
    }
    command.output().unwrap()
}
fn resources(directory: &Path) -> PathBuf {
    let path = directory.join("resources.json");
    std::fs::write(&path,json!({"format":"ken-search-installation/1","grammar_manifest":PathBuf::from(std::env::var_os("KEN_GRAMMAR_MANIFEST").expect("prepared native grammars"))}).to_string()).unwrap();
    path
}
fn value(output: Output) -> Value {
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    serde_json::from_slice(&output.stdout).unwrap()
}
#[test]
fn native_install_tree_parses_host_flags_embedding_budget_and_authenticated_bundle() {
    assert!(matches!(
        args(&["install", ".", "--no-wire", "--embed", "--embed-limit", "0"]),
        InstallationCommand::Install(_)
    ));
    assert!(matches!(
        args(&["install", "--codex", "--deepseek", "--agents-md"]),
        InstallationCommand::Install(_)
    ));
    assert!(matches!(
        args(&["uninstall", "--keep-db"]),
        InstallationCommand::Uninstall(_)
    ));
    assert!(matches!(
        args(&[
            "reinstall",
            "--no-project",
            "--bundle",
            "/fixture/bundle",
            "--manifest-sha256",
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "--prefix",
            "/fixture/prefix"
        ]),
        InstallationCommand::Reinstall(_)
    ));
    assert!(
        ParserFixture::try_parse_from(["ken-rs", "reinstall", "--no-project"]).is_err(),
        "reinstall must declare an authenticated native bundle"
    );
}
#[test]
fn install_no_wire_uses_actual_native_index_without_model_or_ranking_resources() {
    let root = tempfile::tempdir().unwrap();
    let deployment = tempfile::tempdir().unwrap();
    let manifest = resources(deployment.path());
    std::fs::write(
        root.path().join("a.py"),
        "def normalize(value):\n return value.lower()\n",
    )
    .unwrap();
    let first = value(run(
        root.path(),
        &manifest,
        &["install", "--no-wire", "--json"],
    ));
    assert_eq!(first["files_indexed"], 1);
    assert_eq!(first["symbols"], 1);
    let meta = std::fs::read(root.path().join(".ken/meta.json")).unwrap();
    let second = value(run(
        root.path(),
        &manifest,
        &["install", "--no-wire", "--json"],
    ));
    assert_eq!(second["project_id"], first["project_id"]);
    assert_eq!(second["index"]["unchanged"], 1);
    assert_eq!(
        std::fs::read(root.path().join(".ken/meta.json")).unwrap(),
        meta
    );
    assert!(!root.path().join(".mcp.json").exists());
    assert!(!deployment.path().join("models-private").exists());
}
#[test]
fn installed_host_commands_point_to_the_native_executable_and_explicit_resource_manifest() {
    let root = tempfile::tempdir().unwrap();
    let deployment = tempfile::tempdir().unwrap();
    let manifest = resources(deployment.path());
    value(run(
        root.path(),
        &manifest,
        &["install", "--codex", "--agents-md", "--json"],
    ));
    let hooks: Value =
        serde_json::from_slice(&std::fs::read(root.path().join(".codex/hooks.json")).unwrap())
            .unwrap();
    let command = hooks["hooks"]["Stop"][0]["hooks"][0]["command"]
        .as_str()
        .unwrap();
    assert!(command.contains("ken-rs"));
    assert!(command.contains("--resources"));
    assert!(!command.contains("python"));
    assert!(!command.contains("uv "));
    assert!(
        root.path()
            .join(".agents/skills/ken-locate-code/SKILL.md")
            .is_file()
    );
    assert!(root.path().join("AGENTS.md").is_file());
    let text = std::fs::read_to_string(root.path().join(".codex/config.toml")).unwrap();
    assert!(text.contains(manifest.to_string_lossy().as_ref()));
}
#[test]
fn uninstall_requires_no_resource_manifest_never_spawns_a_daemon_and_preserves_edited_configs() {
    let root = tempfile::tempdir().unwrap();
    let deployment = tempfile::tempdir().unwrap();
    let manifest = resources(deployment.path());
    value(run(
        root.path(),
        &manifest,
        &["install", "--codex", "--json"],
    ));
    let config = root.path().join(".codex/config.toml");
    let edited = std::fs::read_to_string(&config).unwrap() + "# keep user edit\n";
    std::fs::write(&config, &edited).unwrap();
    let absent = root.path().join("missing-manifest.json");
    let report = value(run(
        root.path(),
        &absent,
        &["uninstall", "--keep-db", "--json"],
    ));
    assert_eq!(report["removed_project_data"], false);
    assert!(root.path().join(".ken/ken.db").is_file());
    assert!(!root.path().join(".ken/daemon.log").exists());
    assert!(!root.path().join(".ken/daemon.spawn.lock").exists());
    assert_eq!(std::fs::read_to_string(&config).unwrap(), edited);
    let report = value(run(root.path(), &absent, &["uninstall", "--json"]));
    assert_eq!(report["removed_project_data"], true);
    assert!(!root.path().join(".ken").exists());
    assert_eq!(std::fs::read_to_string(config).unwrap(), edited);
}
#[test]
fn native_bundle_authentication_failure_stops_before_project_install_and_no_project_needs_no_grammars()
 {
    let root = tempfile::tempdir().unwrap();
    let deployment = tempfile::tempdir().unwrap();
    let bundle = deployment.path().join("bundle");
    let digest = package_support::bundle(&bundle, Path::new("/bin/true"), None);
    let prefix = deployment.path().join("prefix");
    let missing = root.path().join("missing.json");
    let invalid = "0".repeat(64);
    let arguments = [
        "reinstall",
        "--no-project",
        "--bundle",
        bundle.to_str().unwrap(),
        "--manifest-sha256",
        &invalid,
        "--prefix",
        prefix.to_str().unwrap(),
    ];
    let output = run(root.path(), &missing, &arguments);
    assert!(!output.status.success());
    assert!(!root.path().join(".ken").exists());
    let output = run(
        root.path(),
        &missing,
        &[
            "reinstall",
            "--no-project",
            "--bundle",
            bundle.to_str().unwrap(),
            "--manifest-sha256",
            &digest,
            "--prefix",
            prefix.to_str().unwrap(),
        ],
    );
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(prefix.join("current/ken").is_file());
    assert!(!root.path().join(".ken").exists());
}
#[test]
fn native_reinstall_executes_new_release_and_reapplies_project_only_after_bundle_activation() {
    let root = tempfile::tempdir().unwrap();
    let deployment = tempfile::tempdir().unwrap();
    let bundle = deployment.path().join("bundle");
    let grammar = PathBuf::from(std::env::var_os("KEN_GRAMMAR_MANIFEST").unwrap());
    let digest = package_support::bundle(
        &bundle,
        Path::new(env!("CARGO_BIN_EXE_ken-rs")),
        Some(&grammar),
    );
    let prefix = deployment.path().join("prefix");
    let missing = root.path().join("old-resources-missing.json");
    std::fs::write(root.path().join("a.py"), "def f():\n return 1\n").unwrap();
    let report = value(run(
        root.path(),
        &missing,
        &[
            "reinstall",
            "--bundle",
            bundle.to_str().unwrap(),
            "--manifest-sha256",
            &digest,
            "--prefix",
            prefix.to_str().unwrap(),
            "--codex",
            "--agents-md",
            "--json",
        ],
    ));
    assert_eq!(report["files_indexed"], 1);
    let config = std::fs::read_to_string(root.path().join(".codex/config.toml")).unwrap();
    assert!(
        config.contains(prefix.join("current/ken").to_str().unwrap()),
        "host wiring must use the stable authenticated native launcher"
    );
    assert!(config.contains("resources/search.json"));
    assert!(root.path().join("AGENTS.md").is_file());
    let bad = run(
        root.path(),
        &prefix.join("current/resources/search.json"),
        &["install", "--no-wire", "--embed-limit", "1"],
    );
    assert!(!bad.status.success());
}
