//! Test-only routing and raw stream retention for the copied public executables.
use serde_json::json;
use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
};

pub fn native() -> PathBuf {
    std::env::var_os("KEN_PUBLIC_NATIVE")
        .map(PathBuf::from)
        .unwrap_or_else(|| env!("CARGO_BIN_EXE_ken-rs").into())
}

pub fn application_environment(command: &mut Command) {
    for variable in [
        "KEN_PROJECT_ROOT",
        "KEN_NATIVE_RESOURCES",
        "KEN_ORT_LIBRARY",
        "KEN_GRAMMAR_MANIFEST",
        "KEN_TRANSLATION_SOURCE",
        "KEN_POTION_SOURCE",
        "KEN_CONTEXT_SNAPSHOT",
        "KEN_ETTIN_SOURCE",
        "KEN_CT2_PREPARATION",
        "KEN_CT2_SDK",
        "KEN_PUBLIC_NATIVE",
        "KEN_PUBLIC_RANKS",
        "KEN_PUBLIC_EVIDENCE",
        "CT2_VERBOSE",
    ] {
        command.env_remove(variable);
    }
}

pub fn start(pid: u32, command: &Command, manifest: &Path, project: &Path) -> Option<PathBuf> {
    let root = PathBuf::from(std::env::var_os("KEN_PUBLIC_EVIDENCE")?).join(format!("app-{pid}"));
    fs::create_dir(&root).unwrap();
    let text = |s: &std::ffi::OsStr| s.to_str().unwrap().to_owned();
    let record = json!({"pid":pid,"program":text(command.get_program()),
        "args":command.get_args().map(text).collect::<Vec<_>>(),
        "cwd":command.get_current_dir().unwrap(),
        "environment_changes":command.get_envs().map(|(k,v)|(text(k),v.map(text))).collect::<Vec<_>>(),
        "manifest":manifest,"project":project,"manifest_exists":manifest.exists()});
    fs::write(root.join("invocation.json"), record.to_string()).unwrap();
    if manifest.exists() {
        fs::copy(manifest, root.join("installation.json")).unwrap();
    }
    copy_tree(project, &root.join("project"));
    Some(root)
}

fn copy_tree(source: &Path, destination: &Path) {
    fs::create_dir(destination).unwrap();
    for entry in fs::read_dir(source).unwrap() {
        let entry = entry.unwrap();
        assert!(!entry.file_type().unwrap().is_symlink());
        let target = destination.join(entry.file_name());
        if entry.file_type().unwrap().is_dir() {
            copy_tree(&entry.path(), &target);
        } else {
            fs::copy(entry.path(), target).unwrap();
        }
    }
}
