//! Explicit native helper selection; project PATH never chooses analyzed code.
use std::{
    ffi::OsStr,
    io,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
};
pub fn git_program_from(explicit: Option<&OsStr>, current_exe: &Path) -> io::Result<PathBuf> {
    let candidate = match explicit {
        Some(path) => {
            let path = PathBuf::from(path);
            if !path.is_absolute() {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    "KEN_GIT_PROGRAM must be an absolute executable path",
                ));
            }
            path
        }
        None => current_exe
            .parent()
            .ok_or_else(|| io::Error::other("native executable directory unavailable"))?
            .join("git"),
    };
    let metadata = std::fs::metadata(&candidate).map_err(|error| {
        io::Error::new(
            error.kind(),
            format!(
                "declared native Git unavailable at {}: {error}",
                candidate.display()
            ),
        )
    })?;
    if !metadata.is_file() || metadata.permissions().mode() & 0o111 == 0 {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "declared Git must be a regular executable",
        ));
    }
    Ok(candidate)
}
pub fn git_program() -> io::Result<PathBuf> {
    git_program_from(
        std::env::var_os("KEN_GIT_PROGRAM").as_deref(),
        &std::env::current_exe()?,
    )
}
