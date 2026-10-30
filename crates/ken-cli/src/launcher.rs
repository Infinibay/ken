//! Standard-library-only launcher; native dependency lookup is release-owned.
use std::{
    os::unix::process::CommandExt,
    process::{Command, ExitCode},
};
fn launch() -> std::io::Result<()> {
    let executable = std::env::current_exe()?.canonicalize()?;
    let release = executable
        .parent()
        .ok_or_else(|| std::io::Error::other("native release directory unavailable"))?;
    if release.as_os_str().as_encoded_bytes().contains(&b':') {
        return Err(std::io::Error::other(
            "native release path cannot contain loader separator ':'",
        ));
    }
    let backend = release.join("ken-rs");
    if !std::fs::metadata(&backend)?.is_file() {
        return Err(std::io::Error::other(
            "native CLI sibling is not a regular file",
        ));
    }
    let stable = release
        .parent()
        .filter(|path| path.file_name().is_some_and(|name| name == "releases"))
        .and_then(|path| path.parent())
        .map(|prefix| prefix.join("current/ken"))
        .filter(|path| path.canonicalize().ok().as_ref() == Some(&executable))
        .unwrap_or_else(|| executable.clone());
    let mut command = Command::new(backend);
    command
        .args(std::env::args_os().skip(1))
        .env("LD_LIBRARY_PATH", release.join("lib"))
        .env_remove("LD_PRELOAD")
        .env_remove("LD_AUDIT");
    if std::env::var_os("KEN_NATIVE_INSTALL_EXECUTABLE").is_none() {
        command.env("KEN_NATIVE_INSTALL_EXECUTABLE", &stable);
    }
    if std::env::var_os("KEN_NATIVE_INSTALL_RESOURCES").is_none() {
        command.env(
            "KEN_NATIVE_INSTALL_RESOURCES",
            stable
                .parent()
                .ok_or_else(|| std::io::Error::other("native install directory missing"))?
                .join("resources/search.json"),
        );
    }
    if std::env::var_os("KEN_GIT_PROGRAM").is_none() {
        command.env("KEN_GIT_PROGRAM", release.join("git"));
    }
    let error = command.exec();
    Err(error)
}
fn main() -> ExitCode {
    match launch() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("ken native launcher: {error}");
            ExitCode::FAILURE
        }
    }
}
