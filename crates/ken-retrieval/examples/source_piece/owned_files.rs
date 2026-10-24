//! Scenario filesystem operations stay relative to one private directory handle.
use std::{
    ffi::CString,
    fs::{File, OpenOptions},
    io::{self, Write},
    os::{
        fd::{AsRawFd, FromRawFd},
        unix::{ffi::OsStrExt, fs::OpenOptionsExt},
    },
    path::{Component, Path},
};
pub struct OwnedFiles(File);
fn component(value: &std::ffi::OsStr) -> io::Result<CString> {
    CString::new(value.as_bytes()).map_err(|e| io::Error::new(io::ErrorKind::InvalidInput, e))
}
impl OwnedFiles {
    pub fn new(root: &Path) -> io::Result<Self> {
        Ok(Self(
            OpenOptions::new()
                .read(true)
                .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
                .open(root)?,
        ))
    }
    fn parent(&self, relative: &Path, create: bool) -> io::Result<(File, CString)> {
        let leaf = relative.file_name().ok_or_else(|| {
            io::Error::new(io::ErrorKind::InvalidInput, "owned filename required")
        })?;
        let mut directory = self.0.try_clone()?;
        for part in relative.parent().unwrap_or(Path::new("")).components() {
            if !matches!(part, Component::Normal(_)) {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    "non-confined scenario component",
                ));
            }
            let name = component(part.as_os_str())?;
            if create {
                // SAFETY: the directory descriptor and component string are live.
                let status = unsafe { libc::mkdirat(directory.as_raw_fd(), name.as_ptr(), 0o700) };
                if status < 0 {
                    let error = io::Error::last_os_error();
                    if error.raw_os_error() != Some(libc::EEXIST) {
                        return Err(error);
                    }
                }
            }
            // Never traverse a link, including a link to another owned directory.
            // SAFETY: openat returns a new descriptor owned by the File below.
            let fd = unsafe {
                libc::openat(
                    directory.as_raw_fd(),
                    name.as_ptr(),
                    libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC,
                )
            };
            if fd < 0 {
                return Err(io::Error::last_os_error());
            }
            directory = unsafe { File::from_raw_fd(fd) };
        }
        Ok((directory, component(leaf)?))
    }
    pub fn write(&self, relative: &Path, bytes: &[u8], create_parents: bool) -> io::Result<()> {
        let (parent, name) = self.parent(relative, create_parents)?;
        // Open without truncation, reject nonregular handles, then replace bytes.
        // SAFETY: parent/name are live; successful fd ownership transfers to File.
        let fd = unsafe {
            libc::openat(
                parent.as_raw_fd(),
                name.as_ptr(),
                libc::O_WRONLY
                    | libc::O_CREAT
                    | libc::O_NOFOLLOW
                    | libc::O_CLOEXEC
                    | libc::O_NONBLOCK,
                0o600,
            )
        };
        if fd < 0 {
            return Err(io::Error::last_os_error());
        }
        let mut file = unsafe { File::from_raw_fd(fd) };
        if !file.metadata()?.is_file() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "scenario source is not regular",
            ));
        }
        file.set_len(0)?;
        file.write_all(bytes)
    }
    pub fn directory(&self, relative: &Path) -> io::Result<()> {
        let (parent, name) = self.parent(relative, true)?;
        // SAFETY: both arguments remain valid throughout the syscall.
        if unsafe { libc::mkdirat(parent.as_raw_fd(), name.as_ptr(), 0o700) } < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }
    pub fn remove(&self, relative: &Path) -> io::Result<()> {
        let (parent, name) = self.parent(relative, false)?;
        // unlinkat removes the leaf itself and never follows a leaf symlink.
        // SAFETY: both arguments remain valid throughout the syscall.
        if unsafe { libc::unlinkat(parent.as_raw_fd(), name.as_ptr(), 0) } < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }
    pub fn symlink(&self, target: &Path, relative: &Path, create_parents: bool) -> io::Result<()> {
        let (parent, name) = self.parent(relative, create_parents)?;
        let target = component(target.as_os_str())?;
        // SAFETY: target/name and parent descriptor remain live.
        if unsafe { libc::symlinkat(target.as_ptr(), parent.as_raw_fd(), name.as_ptr()) } < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }
    pub fn rename(&self, from: &Path, to: &Path) -> io::Result<()> {
        let (source, from) = self.parent(from, false)?;
        let (destination, to) = self.parent(to, false)?;
        // SAFETY: both directory descriptors and component strings remain live.
        if unsafe {
            libc::renameat(
                source.as_raw_fd(),
                from.as_ptr(),
                destination.as_raw_fd(),
                to.as_ptr(),
            )
        } < 0
        {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }
}
