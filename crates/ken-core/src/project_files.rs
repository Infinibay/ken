//! Descriptor-confined project files and durable publication, shared by host and
//! project installation policy. Managed components never follow user symlinks.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("{0}")]
    Invalid(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
}
pub type Result<T> = std::result::Result<T, Error>;
fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
use std::{
    ffi::{CString, OsStr},
    fs::{File, OpenOptions},
    io::{Read, Write},
    os::{
        fd::{AsRawFd, FromRawFd},
        unix::{
            ffi::OsStrExt,
            fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
        },
    },
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
    time::{Duration, Instant},
};
pub const MAX_BYTES: usize = 16 * 1024 * 1024;
pub fn parts(value: &str) -> Result<Vec<&str>> {
    if value.is_empty()
        || value.starts_with('/')
        || value.contains(['\\', '\0'])
        || value
            .split('/')
            .any(|p| p.is_empty() || p == "." || p == "..")
    {
        return Err(invalid(format!("Invalid managed resource path: {value:?}")));
    }
    Ok(value.split('/').collect())
}
fn cstring(value: &OsStr) -> Result<CString> {
    CString::new(value.as_bytes()).map_err(|_| invalid("managed path contains NUL"))
}
fn cpart(value: &str) -> Result<CString> {
    cstring(OsStr::new(value))
}
fn opened(fd: i32) -> Result<File> {
    if fd < 0 {
        Err(std::io::Error::last_os_error().into())
    } else {
        Ok(unsafe { File::from_raw_fd(fd) })
    }
}
pub struct ProjectFiles {
    pub path: PathBuf,
    file: File,
}
pub struct Lock(File);
impl Drop for Lock {
    fn drop(&mut self) {
        unsafe {
            libc::flock(self.0.as_raw_fd(), libc::LOCK_UN);
        }
    }
}
impl ProjectFiles {
    pub fn new(root: &Path) -> Result<Self> {
        let path = root.canonicalize()?;
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(&path)?;
        Ok(Self { path, file })
    }
    pub fn duplicate(&self) -> Result<Self> {
        self.check()?;
        Ok(Self {
            path: self.path.clone(),
            file: self.file.try_clone()?,
        })
    }
    fn check(&self) -> Result<()> {
        let named = std::fs::symlink_metadata(&self.path)?;
        let held = self.file.metadata()?;
        if !named.is_dir()
            || named.file_type().is_symlink()
            || named.dev() != held.dev()
            || named.ino() != held.ino()
        {
            return Err(invalid(
                "project root changed while accessing managed files",
            ));
        }
        Ok(())
    }
    pub fn lock(&self) -> Result<Lock> {
        self.check()?;
        let file = opened(unsafe {
            libc::openat(
                self.file.as_raw_fd(),
                c".".as_ptr(),
                libc::O_RDONLY | libc::O_DIRECTORY | libc::O_CLOEXEC,
            )
        })?;
        let start = Instant::now();
        loop {
            if unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0 {
                return Ok(Lock(file));
            }
            let e = std::io::Error::last_os_error();
            if e.raw_os_error() != Some(libc::EWOULDBLOCK) {
                return Err(e.into());
            }
            if start.elapsed() > Duration::from_secs(5) {
                return Err(invalid("project file lock budget exhausted"));
            }
            std::thread::sleep(Duration::from_millis(10));
        }
    }
    fn child(
        &self,
        parent: &File,
        name: &str,
        relative: &str,
        create: bool,
    ) -> Result<Option<File>> {
        let name = cpart(name)?;
        let flags = libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC;
        let mut fd = unsafe { libc::openat(parent.as_raw_fd(), name.as_ptr(), flags) };
        if fd < 0
            && std::io::Error::last_os_error().kind() == std::io::ErrorKind::NotFound
            && create
        {
            if unsafe { libc::mkdirat(parent.as_raw_fd(), name.as_ptr(), 0o777) } < 0
                && std::io::Error::last_os_error().kind() != std::io::ErrorKind::AlreadyExists
            {
                return Err(std::io::Error::last_os_error().into());
            }
            parent.sync_all()?;
            fd = unsafe { libc::openat(parent.as_raw_fd(), name.as_ptr(), flags) };
        }
        if fd >= 0 {
            return Ok(Some(unsafe { File::from_raw_fd(fd) }));
        }
        let error = std::io::Error::last_os_error();
        if error.kind() == std::io::ErrorKind::NotFound {
            return Ok(None);
        }
        let mut stat = std::mem::MaybeUninit::<libc::stat>::uninit();
        if unsafe {
            libc::fstatat(
                parent.as_raw_fd(),
                name.as_ptr(),
                stat.as_mut_ptr(),
                libc::AT_SYMLINK_NOFOLLOW,
            )
        } == 0
            && unsafe { stat.assume_init() }.st_mode & libc::S_IFMT == libc::S_IFLNK
        {
            return Err(invalid(format!("Managed path is a symlink: {relative}")));
        }
        Err(error.into())
    }
    fn parent(&self, relative: &str, create: bool) -> Result<Option<(File, CString)>> {
        self.check()?;
        let components = parts(relative)?;
        let mut directory = self.file.try_clone()?;
        for name in &components[..components.len() - 1] {
            let Some(next) = self.child(&directory, name, relative, create)? else {
                return Ok(None);
            };
            directory = next;
        }
        Ok(Some((directory, cpart(components[components.len() - 1])?)))
    }
    pub fn read(&self, relative: &str) -> Result<Option<Vec<u8>>> {
        let Some((directory, name)) = self.parent(relative, false)? else {
            return Ok(None);
        };
        let fd = unsafe {
            libc::openat(
                directory.as_raw_fd(),
                name.as_ptr(),
                libc::O_RDONLY | libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC,
            )
        };
        if fd < 0 {
            let error = std::io::Error::last_os_error();
            if error.kind() == std::io::ErrorKind::NotFound {
                return Ok(None);
            }
            if error.raw_os_error() == Some(libc::ELOOP) {
                return Err(invalid(format!("Managed path is a symlink: {relative}")));
            }
            return Err(error.into());
        }
        let mut file = unsafe { File::from_raw_fd(fd) };
        let before = file.metadata()?;
        if !before.is_file() {
            return Err(invalid(format!(
                "Managed resource is not a regular file: {relative}"
            )));
        }
        if before.len() > MAX_BYTES as u64 {
            return Err(invalid("managed file byte budget exhausted"));
        }
        let mut bytes = Vec::new();
        Read::by_ref(&mut file)
            .take(MAX_BYTES as u64 + 1)
            .read_to_end(&mut bytes)?;
        let after = file.metadata()?;
        if bytes.len() > MAX_BYTES {
            return Err(invalid("managed file byte budget exhausted"));
        }
        let stamp = |m: &std::fs::Metadata| {
            (
                m.dev(),
                m.ino(),
                m.len(),
                m.mtime(),
                m.mtime_nsec(),
                m.ctime(),
                m.ctime_nsec(),
            )
        };
        let mut named = std::mem::MaybeUninit::<libc::stat>::uninit();
        if unsafe {
            libc::fstatat(
                directory.as_raw_fd(),
                name.as_ptr(),
                named.as_mut_ptr(),
                libc::AT_SYMLINK_NOFOLLOW,
            )
        } < 0
        {
            return Err(invalid("managed file changed during inspection"));
        }
        let named = unsafe { named.assume_init() };
        if stamp(&before) != stamp(&after)
            || after.dev() != named.st_dev
            || after.ino() != named.st_ino
            || named.st_mode & libc::S_IFMT != libc::S_IFREG
        {
            return Err(invalid("managed file changed during inspection"));
        }
        Ok(Some(bytes))
    }
    pub fn exists(&self, relative: &str) -> Result<bool> {
        let Some((directory, name)) = self.parent(relative, false)? else {
            return Ok(false);
        };
        let mut stat = std::mem::MaybeUninit::<libc::stat>::uninit();
        if unsafe {
            libc::fstatat(
                directory.as_raw_fd(),
                name.as_ptr(),
                stat.as_mut_ptr(),
                libc::AT_SYMLINK_NOFOLLOW,
            )
        } < 0
        {
            let e = std::io::Error::last_os_error();
            if e.kind() == std::io::ErrorKind::NotFound {
                return Ok(false);
            }
            return Err(e.into());
        }
        let stat = unsafe { stat.assume_init() };
        if stat.st_mode & libc::S_IFMT == libc::S_IFLNK {
            return Err(invalid(format!("Managed path is a symlink: {relative}")));
        }
        Ok(true)
    }
    pub fn is_file(&self, relative: &str) -> Result<bool> {
        let Some((directory, name)) = self.parent(relative, false)? else {
            return Ok(false);
        };
        let mut stat = std::mem::MaybeUninit::<libc::stat>::uninit();
        if unsafe {
            libc::fstatat(
                directory.as_raw_fd(),
                name.as_ptr(),
                stat.as_mut_ptr(),
                libc::AT_SYMLINK_NOFOLLOW,
            )
        } < 0
        {
            let error = std::io::Error::last_os_error();
            if error.kind() == std::io::ErrorKind::NotFound {
                return Ok(false);
            }
            return Err(error.into());
        }
        let stat = unsafe { stat.assume_init() };
        if stat.st_mode & libc::S_IFMT == libc::S_IFLNK {
            return Err(invalid(format!("Managed path is a symlink: {relative}")));
        }
        Ok(stat.st_mode & libc::S_IFMT == libc::S_IFREG)
    }
    fn directory(&self, relative: &str) -> Result<Option<File>> {
        let mut handle = self.file.try_clone()?;
        for part in parts(relative)? {
            let Some(next) = self.child(&handle, part, relative, false)? else {
                return Ok(None);
            };
            handle = next;
        }
        Ok(Some(handle))
    }
    pub fn is_directory(&self, relative: &str) -> Result<bool> {
        match self.directory(relative) {
            Ok(file) => Ok(file.is_some()),
            Err(Error::Io(e)) if e.kind() == std::io::ErrorKind::NotADirectory => Ok(false),
            Err(e) => Err(e),
        }
    }
    pub fn nonempty_directory(&self, relative: &str) -> Result<bool> {
        if !self.is_directory(relative)? {
            return Ok(false);
        }
        let Some(file) = self.directory(relative)? else {
            return Ok(false);
        };
        Ok(
            std::fs::read_dir(format!("/proc/self/fd/{}", file.as_raw_fd()))?
                .next()
                .transpose()?
                .is_some(),
        )
    }
    pub fn add_owner_write(&self, relative: &str) -> Result<()> {
        if let Some(directory) = self.directory(relative)? {
            let mode = directory.metadata()?.permissions().mode();
            if mode & 0o200 == 0 && unsafe { libc::fchmod(directory.as_raw_fd(), mode | 0o200) } < 0
            {
                return Err(std::io::Error::last_os_error().into());
            }
        }
        Ok(())
    }
    pub fn write(&self, relative: &str, bytes: &[u8]) -> Result<()> {
        if bytes.len() > MAX_BYTES {
            return Err(invalid("managed file byte budget exhausted"));
        }
        let (directory, name) = self.parent(relative, true)?.expect("created parent");
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let mut temporary = None;
        for _ in 0..64 {
            let raw = format!(
                ".ken-write-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            );
            let candidate = cpart(&raw)?;
            let fd = unsafe {
                libc::openat(
                    directory.as_raw_fd(),
                    candidate.as_ptr(),
                    libc::O_WRONLY
                        | libc::O_CREAT
                        | libc::O_EXCL
                        | libc::O_NOFOLLOW
                        | libc::O_CLOEXEC,
                    0o600,
                )
            };
            if fd >= 0 {
                temporary = Some((candidate, unsafe { File::from_raw_fd(fd) }));
                break;
            }
            if std::io::Error::last_os_error().kind() != std::io::ErrorKind::AlreadyExists {
                return Err(std::io::Error::last_os_error().into());
            }
        }
        let (temporary, mut file) = temporary
            .ok_or_else(|| invalid("atomic project writer temporary-name budget exhausted"))?;
        let result = (|| -> Result<()> {
            let mut previous = std::mem::MaybeUninit::<libc::stat>::uninit();
            if unsafe {
                libc::fstatat(
                    directory.as_raw_fd(),
                    name.as_ptr(),
                    previous.as_mut_ptr(),
                    libc::AT_SYMLINK_NOFOLLOW,
                )
            } == 0
            {
                let old = unsafe { previous.assume_init() };
                if old.st_mode & libc::S_IFMT != libc::S_IFREG {
                    return Err(invalid("managed write target is not a regular file"));
                }
                if unsafe { libc::fchmod(file.as_raw_fd(), old.st_mode & 0o7777) } < 0 {
                    return Err(std::io::Error::last_os_error().into());
                }
            }
            file.write_all(bytes)?;
            file.sync_all()?;
            if unsafe {
                libc::renameat(
                    directory.as_raw_fd(),
                    temporary.as_ptr(),
                    directory.as_raw_fd(),
                    name.as_ptr(),
                )
            } < 0
            {
                return Err(std::io::Error::last_os_error().into());
            }
            directory.sync_all()?;
            Ok(())
        })();
        unsafe {
            libc::unlinkat(directory.as_raw_fd(), temporary.as_ptr(), 0);
        }
        result
    }
    pub fn remove(&self, relative: &str) -> Result<()> {
        let Some((directory, name)) = self.parent(relative, false)? else {
            return Ok(());
        };
        if unsafe { libc::unlinkat(directory.as_raw_fd(), name.as_ptr(), 0) } < 0 {
            let e = std::io::Error::last_os_error();
            if e.kind() != std::io::ErrorKind::NotFound {
                return Err(e.into());
            }
        }
        directory.sync_all()?;
        Ok(())
    }
    pub fn prune(&self, relative: &str, boundary: &str) {
        let mut path = relative.to_owned();
        while path == boundary || path.starts_with(&format!("{boundary}/")) {
            let Ok(Some((directory, name))) = self.parent(&path, false) else {
                break;
            };
            if unsafe { libc::unlinkat(directory.as_raw_fd(), name.as_ptr(), libc::AT_REMOVEDIR) }
                < 0
            {
                break;
            }
            let _ = directory.sync_all();
            let Some((parent, _)) = path.rsplit_once('/') else {
                break;
            };
            path = parent.into();
        }
    }
    /// Hold a named directory without following any component symlink.
    pub fn directory_handle(&self, relative: &str, create: bool) -> Result<Option<File>> {
        self.check()?;
        let mut handle = self.file.try_clone()?;
        for part in parts(relative)? {
            let Some(next) = self.child(&handle, part, relative, create)? else {
                return Ok(None);
            };
            handle = next;
        }
        Ok(Some(handle))
    }
    /// Require the named directory to retain the exact held identity.
    pub fn check_directory(&self, relative: &str, held: &File) -> Result<()> {
        let named = self
            .directory_handle(relative, false)?
            .ok_or_else(|| invalid("managed directory disappeared"))?;
        let a = named.metadata()?;
        let b = held.metadata()?;
        if a.dev() != b.dev() || a.ino() != b.ino() {
            return Err(invalid("managed directory identity changed"));
        }
        Ok(())
    }
    /// Remove an explicitly held generation; traversal unlinks symlinks as leaves.
    pub fn remove_tree(&self, relative: &str, held: &File) -> Result<()> {
        self.check_directory(relative, held)?;
        let mut remaining = 100_000usize;
        remove_contents(held, &mut remaining, 0)?;
        self.check_directory(relative, held)?;
        let (parent, name) = self
            .parent(relative, false)?
            .ok_or_else(|| invalid("managed directory disappeared"))?;
        if unsafe { libc::unlinkat(parent.as_raw_fd(), name.as_ptr(), libc::AT_REMOVEDIR) } < 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        parent.sync_all()?;
        Ok(())
    }
}

fn remove_contents(directory: &File, remaining: &mut usize, depth: usize) -> Result<()> {
    if depth > 128 {
        return Err(invalid("project removal depth budget exhausted"));
    }
    for entry in std::fs::read_dir(format!("/proc/self/fd/{}", directory.as_raw_fd()))? {
        if *remaining == 0 {
            return Err(invalid("project removal entry budget exhausted"));
        }
        *remaining -= 1;
        let entry = entry?;
        let name = cstring(&entry.file_name())?;
        let mut value = std::mem::MaybeUninit::<libc::stat>::uninit();
        if unsafe {
            libc::fstatat(
                directory.as_raw_fd(),
                name.as_ptr(),
                value.as_mut_ptr(),
                libc::AT_SYMLINK_NOFOLLOW,
            )
        } < 0
        {
            return Err(std::io::Error::last_os_error().into());
        }
        let value = unsafe { value.assume_init() };
        let is_directory = value.st_mode & libc::S_IFMT == libc::S_IFDIR;
        if is_directory {
            let child = opened(unsafe {
                libc::openat(
                    directory.as_raw_fd(),
                    name.as_ptr(),
                    libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC,
                )
            })?;
            let metadata = child.metadata()?;
            if metadata.dev() != value.st_dev || metadata.ino() != value.st_ino {
                return Err(invalid("project removal directory changed"));
            }
            remove_contents(&child, remaining, depth + 1)?;
            let mut current = std::mem::MaybeUninit::<libc::stat>::uninit();
            if unsafe {
                libc::fstatat(
                    directory.as_raw_fd(),
                    name.as_ptr(),
                    current.as_mut_ptr(),
                    libc::AT_SYMLINK_NOFOLLOW,
                )
            } < 0
            {
                return Err(std::io::Error::last_os_error().into());
            }
            let current = unsafe { current.assume_init() };
            if current.st_dev != value.st_dev || current.st_ino != value.st_ino {
                return Err(invalid("project removal directory changed"));
            }
        }
        if unsafe {
            libc::unlinkat(
                directory.as_raw_fd(),
                name.as_ptr(),
                if is_directory { libc::AT_REMOVEDIR } else { 0 },
            )
        } < 0
        {
            return Err(std::io::Error::last_os_error().into());
        }
    }
    directory.sync_all()?;
    Ok(())
}
