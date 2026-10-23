//! Directory enumeration through a root-owned handle, without following replacements.
use std::{ffi::OsString, fs::File, io, path::Path};

#[cfg(unix)]
pub(crate) fn read_names(root: &File, relative: &Path) -> io::Result<Vec<OsString>> {
    use std::{
        ffi::{CStr, CString},
        os::{
            fd::{AsRawFd, FromRawFd, IntoRawFd},
            unix::ffi::{OsStrExt, OsStringExt},
        },
    };
    let mut handle = root.try_clone()?;
    for component in relative.components() {
        let name = CString::new(component.as_os_str().as_bytes())?;
        // SAFETY: both the borrowed descriptor and nul-terminated name are valid.
        // Each component is opened relative to the preceding held directory;
        // symlink replacements cannot redirect openat to an external directory.
        let fd = unsafe {
            libc::openat(
                handle.as_raw_fd(),
                name.as_ptr(),
                libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC,
            )
        };
        if fd < 0 {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: openat returned a new descriptor exclusively owned here.
        handle = unsafe { File::from_raw_fd(fd) };
    }
    // fdopendir takes descriptor ownership only on success.
    let fd = handle.into_raw_fd();
    let stream = unsafe { libc::fdopendir(fd) };
    if stream.is_null() {
        let error = io::Error::last_os_error();
        unsafe {
            libc::close(fd);
        }
        return Err(error);
    }
    struct Stream(*mut libc::DIR);
    impl Drop for Stream {
        fn drop(&mut self) {
            unsafe {
                libc::closedir(self.0);
            }
        }
    }
    let stream = Stream(stream);
    let mut names = Vec::new();
    loop {
        // readdir's null result distinguishes EOF from failure through errno.
        #[cfg(target_os = "macos")]
        let errno = unsafe { libc::__error() };
        #[cfg(not(target_os = "macos"))]
        let errno = unsafe { libc::__errno_location() };
        unsafe {
            *errno = 0;
        }
        let entry = unsafe { libc::readdir(stream.0) };
        if entry.is_null() {
            let error = unsafe { *errno };
            return if error == 0 {
                Ok(names)
            } else {
                Err(io::Error::from_raw_os_error(error))
            };
        }
        // SAFETY: readdir's entry is valid until the next call, and d_name is
        // nul terminated. Copy the name before advancing or closing the stream.
        let bytes = unsafe { CStr::from_ptr((*entry).d_name.as_ptr()) }.to_bytes();
        if bytes != b"." && bytes != b".." {
            names.push(OsString::from_vec(bytes.to_vec()));
        }
    }
}
