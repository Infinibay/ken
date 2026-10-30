//! One held rule directory owns locking, atomic replacement and durable cleanup.
use super::*;
use ken_core::project::{DiscoveryContext, ProjectPaths};
use std::{
    ffi::CString,
    fs::File,
    io::Write,
    os::fd::{AsRawFd, FromRawFd},
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
};
static NEXT: AtomicU64 = AtomicU64::new(0);
struct Directory(File);
fn name(value: &str) -> Result<CString> {
    CString::new(value).map_err(|_| invalid("invalid rule filename"))
}
impl Directory {
    fn child(&self, value: &str) -> Result<Self> {
        let value = name(value)?;
        // SAFETY: self retains the directory descriptor and CString is NUL terminated.
        if unsafe { libc::mkdirat(self.0.as_raw_fd(), value.as_ptr(), 0o700) } < 0
            && std::io::Error::last_os_error().kind() != std::io::ErrorKind::AlreadyExists
        {
            return Err(std::io::Error::last_os_error().into());
        }
        let fd = unsafe {
            libc::openat(
                self.0.as_raw_fd(),
                value.as_ptr(),
                libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC,
            )
        };
        if fd < 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        Ok(Self(unsafe { File::from_raw_fd(fd) }))
    }
    fn file(&self, value: &str, flags: i32) -> Result<File> {
        let value = name(value)?;
        let fd = unsafe {
            libc::openat(
                self.0.as_raw_fd(),
                value.as_ptr(),
                flags | libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK,
                0o600,
            )
        };
        if fd < 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        let file = unsafe { File::from_raw_fd(fd) };
        if !file.metadata()?.is_file() {
            return Err(invalid("rule state must be a regular file"));
        }
        Ok(file)
    }
    fn publish(&self, target: &str, content: &str) -> Result<()> {
        if content.len() > 16_000_000 {
            return Err(invalid("rule document exceeds 16 MB"));
        }
        let temporary = format!(
            ".rule-{}-{}.tmp",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        );
        let mut file = self.file(&temporary, libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL)?;
        let result = (|| {
            file.write_all(content.as_bytes())?;
            file.sync_all()?;
            let source = name(&temporary)?;
            let target = name(target)?;
            if unsafe {
                libc::renameat(
                    self.0.as_raw_fd(),
                    source.as_ptr(),
                    self.0.as_raw_fd(),
                    target.as_ptr(),
                )
            } < 0
            {
                return Err(std::io::Error::last_os_error().into());
            }
            self.0.sync_all()?;
            Ok(())
        })();
        let temporary = name(&temporary)?;
        unsafe { libc::unlinkat(self.0.as_raw_fd(), temporary.as_ptr(), 0) };
        result
    }
}
struct Lock(File);
impl Drop for Lock {
    fn drop(&mut self) {
        unsafe { libc::flock(self.0.as_raw_fd(), libc::LOCK_UN) };
    }
}
pub(super) fn save(
    root: &Path,
    rule: &SavedRule,
    overwrite: bool,
    catalog: &Catalog,
) -> Result<PathBuf> {
    let context = DiscoveryContext::from_process()?;
    let paths = ProjectPaths::at(root, &context)?;
    let directory = Directory(paths.open_root()?)
        .child(".ken")?
        .child("rules")?;
    let file = directory.file(".write.lock", libc::O_WRONLY | libc::O_CREAT)?;
    loop {
        if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX) } == 0 {
            break;
        }
        let error = std::io::Error::last_os_error();
        if error.kind() != std::io::ErrorKind::Interrupted {
            return Err(error.into());
        }
    }
    let _lock = Lock(file);
    let current = RuleLibrary::load(paths.root(), catalog, &[])?;
    let target = paths.resolve_inside(
        &Path::new(".ken/rules").join(format!("{}.toml", rule.id)),
        &context,
    )?;
    if let Some(previous) = current.rules().iter().find(|r| r.id == rule.id) {
        if !overwrite || !previous.source.is_empty() {
            return Err(invalid(format!(
                "rule {} already exists; built-in ids are reserved; use --overwrite for a custom file",
                rule.id
            )));
        }
        if !target.exists() {
            return Err(invalid(
                "rule is defined in another library; edit its source file instead",
            ));
        }
    } else if current.queries()?.contains_key(&rule.id) {
        return Err(invalid(format!(
            "rule {} is a reserved named query",
            rule.id
        )));
    }
    // Validate the complete replacement closure while the same writer lock is held.
    let mut replacements = current.rules.clone();
    replacements.retain(|r| r.id != rule.id);
    replacements.push(rule.clone());
    super::library::build_queries(&replacements, catalog)?;
    let mut value = serde_json::to_value(rule)?;
    let object = value.as_object_mut().unwrap();
    object.remove("variants");
    object.remove("source");
    object.retain(|_, v| !v.is_null());
    let content = toml::to_string(&value)?;
    directory.publish(&format!("{}.toml", rule.id), &content)?;
    Ok(target)
}
