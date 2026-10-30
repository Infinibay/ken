//! Process ownership of runtime advertisement; locks outlive their file names.
use crate::{Error, Result};
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    os::{fd::AsRawFd, unix::fs::OpenOptionsExt},
    path::{Path, PathBuf},
};
pub(crate) struct FileLock(File);
impl FileLock {
    pub(crate) fn acquire(path: &Path, nonblocking: bool) -> Result<Self> {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .open(path)?;
        let operation = libc::LOCK_EX | if nonblocking { libc::LOCK_NB } else { 0 };
        if unsafe { libc::flock(file.as_raw_fd(), operation) } != 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        Ok(Self(file))
    }
}
impl Drop for FileLock {
    fn drop(&mut self) {
        unsafe { libc::flock(self.0.as_raw_fd(), libc::LOCK_UN) };
    }
}
pub(crate) struct RuntimeFiles {
    root: PathBuf,
    port: u16,
    pid: u32,
    _lock: FileLock,
}
impl RuntimeFiles {
    pub(crate) fn publish(root: &Path, port: u16) -> Result<Self> {
        let dir = root.join(".ken");
        let lock = FileLock::acquire(&dir.join("daemon.lock"), true).map_err(|e| {
            Error::Invalid(format!("daemon already running or lock unavailable: {e}"))
        })?;
        let pid = std::process::id();
        let owner = Self {
            root: root.into(),
            port,
            pid,
            _lock: lock,
        };
        atomic_write(&dir.join("daemon.pid"), &pid.to_string())?;
        atomic_write(&dir.join("daemon.port"), &port.to_string())?;
        Ok(owner)
    }
}
fn atomic_write(path: &Path, text: &str) -> Result<()> {
    let temporary = path.with_extension(format!("tmp.{}", std::process::id()));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&temporary)?;
    let result = (|| -> Result<()> {
        file.write_all(text.as_bytes())?;
        file.sync_all()?;
        fs::rename(&temporary, path)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}
impl Drop for RuntimeFiles {
    fn drop(&mut self) {
        let dir = self.root.join(".ken");
        let same_pid = fs::read_to_string(dir.join("daemon.pid"))
            .ok()
            .and_then(|s| s.trim().parse::<u32>().ok())
            == Some(self.pid);
        let same_port = fs::read_to_string(dir.join("daemon.port"))
            .ok()
            .and_then(|s| s.trim().parse::<u16>().ok())
            == Some(self.port);
        if same_pid && same_port {
            let _ = fs::remove_file(dir.join("daemon.port"));
            let _ = fs::remove_file(dir.join("daemon.pid"));
        }
    }
}
