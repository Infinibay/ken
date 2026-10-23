//! Component-relative source access from a held project root.
use std::{
    ffi::CString,
    fs::File,
    io,
    os::{
        fd::{AsRawFd, FromRawFd},
        unix::ffi::OsStrExt,
    },
    path::{Component, Path},
};
pub(crate) fn open(root: &File, relative: &Path, directory: bool) -> io::Result<File> {
    let mut handle = root.try_clone()?;
    let mut components = relative.components().peekable();
    while let Some(component) = components.next() {
        if !matches!(component, Component::Normal(_)) {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "source path is not a confined component",
            ));
        }
        let name = CString::new(component.as_os_str().as_bytes())?;
        let flags = libc::O_RDONLY
            | libc::O_NOFOLLOW
            | libc::O_CLOEXEC
            | if components.peek().is_some() || directory {
                libc::O_DIRECTORY
            } else {
                libc::O_NONBLOCK
            };
        // SAFETY: directory descriptor and nul-terminated component remain live;
        // openat returns a new owned descriptor, or an error without ownership.
        let fd = unsafe { libc::openat(handle.as_raw_fd(), name.as_ptr(), flags) };
        if fd < 0 {
            return Err(io::Error::last_os_error());
        }
        handle = unsafe { File::from_raw_fd(fd) };
    }
    Ok(handle)
}

pub(crate) fn open_root(path: &Path) -> io::Result<File> {
    let filesystem = File::open("/")?;
    let relative = path.strip_prefix("/").map_err(|_| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "absolute canonical source root required",
        )
    })?;
    open(&filesystem, relative, true)
}
