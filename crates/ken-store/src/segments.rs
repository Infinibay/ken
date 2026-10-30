//! Fixed file publication and owned positional I/O. No file-backed borrowed slices.
use crate::{StoreError, StoreResult};
use std::{
    collections::BTreeSet,
    ffi::{CString, OsStr},
    fs::{File, OpenOptions},
    io,
    os::{
        fd::{AsRawFd, FromRawFd},
        unix::{
            ffi::OsStrExt,
            fs::{FileExt, MetadataExt, OpenOptionsExt},
        },
    },
    path::{Component, Path, PathBuf},
    sync::{
        Mutex,
        atomic::{AtomicU64, Ordering},
    },
};

/// Prepare privately, then publish one complete inode exclusively. Normal creation
/// applies umask without reading/changing process-global state. A loser never truncates.
pub(crate) fn publish_new(
    path: &Path,
    prepare: impl FnOnce(&mut File) -> io::Result<()>,
) -> StoreResult<bool> {
    let parent = path
        .parent()
        .ok_or(StoreError::InvalidSlot("file has no parent"))?;
    let temporary = tempfile::Builder::new()
        .prefix(".ken-publish-")
        .tempdir_in(parent)
        .map_err(|e| StoreError::io(parent, e))?;
    let prepared = temporary.path().join("prepared");
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&prepared)
        .map_err(|e| StoreError::io(&prepared, e))?;
    prepare(&mut file).map_err(|e| StoreError::io(&prepared, e))?;
    file.sync_all().map_err(|e| StoreError::io(&prepared, e))?;
    match std::fs::hard_link(&prepared, path) {
        Ok(()) => {
            File::open(parent)
                .and_then(|f| f.sync_all())
                .map_err(|e| StoreError::io(parent, e))?;
            Ok(true)
        }
        Err(e) if e.kind() == io::ErrorKind::AlreadyExists => Ok(false),
        Err(e) => Err(StoreError::io(path, e)),
    }
}

/// A segment space owns its directory descriptor. Every segment is opened
/// relative to that descriptor without following user-controlled symlinks.
pub(crate) struct Segments {
    pub directory: PathBuf,
    pub space: crate::VectorSpace,
    pub capacity: u64,
    absolute_directory: PathBuf,
    handle: File,
}
fn component_name(value: &OsStr) -> io::Result<CString> {
    CString::new(value.as_bytes())
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "vector path contains NUL"))
}
fn opened(fd: i32) -> io::Result<File> {
    if fd < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(unsafe { File::from_raw_fd(fd) })
    }
}
fn directory_handle(path: &Path) -> io::Result<File> {
    let mut directory = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open("/")?;
    for part in path.components() {
        let component = match part {
            Component::RootDir | Component::CurDir => continue,
            Component::ParentDir => OsStr::new(".."),
            Component::Normal(value) => value,
            Component::Prefix(_) => {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    "unsupported vector path prefix",
                ));
            }
        };
        let component = component_name(component)?;
        directory = opened(unsafe {
            libc::openat(
                directory.as_raw_fd(),
                component.as_ptr(),
                libc::O_RDONLY | libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC,
            )
        })?;
    }
    Ok(directory)
}
impl Segments {
    pub fn new(directory: &Path, space: crate::VectorSpace, capacity: u64) -> StoreResult<Self> {
        let absolute_directory =
            std::path::absolute(directory).map_err(|e| StoreError::io(directory, e))?;
        let handle =
            directory_handle(&absolute_directory).map_err(|e| StoreError::io(directory, e))?;
        let segments = Self {
            directory: directory.into(),
            space,
            capacity,
            absolute_directory,
            handle,
        };
        segments.check_directory()?;
        Ok(segments)
    }
    pub fn path(&self, index: u64) -> PathBuf {
        self.directory
            .join(format!("{}.{index:04}.vec", self.space))
    }
    fn check_directory(&self) -> StoreResult<()> {
        let named = std::fs::symlink_metadata(&self.absolute_directory)
            .map_err(|e| StoreError::io(&self.directory, e))?;
        let held = self
            .handle
            .metadata()
            .map_err(|e| StoreError::io(&self.directory, e))?;
        if !named.is_dir()
            || named.file_type().is_symlink()
            || named.dev() != held.dev()
            || named.ino() != held.ino()
        {
            return Err(StoreError::io(
                &self.directory,
                io::Error::new(
                    io::ErrorKind::InvalidData,
                    "vector directory identity changed",
                ),
            ));
        }
        Ok(())
    }
    fn filename(&self, index: u64) -> CString {
        CString::new(format!("{}.{index:04}.vec", self.space))
            .expect("fixed vector space and integer filename")
    }
    fn open_named(&self, name: &CString, write: bool) -> io::Result<File> {
        opened(unsafe {
            libc::openat(
                self.handle.as_raw_fd(),
                name.as_ptr(),
                (if write { libc::O_RDWR } else { libc::O_RDONLY })
                    | libc::O_NOFOLLOW
                    | libc::O_NONBLOCK
                    | libc::O_CLOEXEC,
            )
        })
    }
    fn check_file(&self, index: u64, file: &File) -> StoreResult<()> {
        self.check_directory()?;
        let path = self.path(index);
        let held = file.metadata().map_err(|e| StoreError::io(&path, e))?;
        let mut named = std::mem::MaybeUninit::<libc::stat>::uninit();
        let filename = self.filename(index);
        if unsafe {
            libc::fstatat(
                self.handle.as_raw_fd(),
                filename.as_ptr(),
                named.as_mut_ptr(),
                libc::AT_SYMLINK_NOFOLLOW,
            )
        } < 0
        {
            return Err(StoreError::io(&path, io::Error::last_os_error()));
        }
        let named = unsafe { named.assume_init() };
        if !held.is_file()
            || held.len() != self.capacity
            || named.st_mode & libc::S_IFMT != libc::S_IFREG
            || named.st_dev != held.dev()
            || named.st_ino != held.ino()
        {
            return Err(StoreError::io(
                &path,
                io::Error::new(
                    io::ErrorKind::InvalidData,
                    "segment identity or full fixed capacity differs",
                ),
            ));
        }
        Ok(())
    }
    fn publish(&self, index: u64) -> StoreResult<()> {
        self.check_directory()?;
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let mut prepared = None;
        for _ in 0..64 {
            let filename = CString::new(format!(
                ".ken-segment-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ))
            .unwrap();
            let fd = unsafe {
                libc::openat(
                    self.handle.as_raw_fd(),
                    filename.as_ptr(),
                    libc::O_WRONLY
                        | libc::O_CREAT
                        | libc::O_EXCL
                        | libc::O_NOFOLLOW
                        | libc::O_CLOEXEC,
                    0o666,
                )
            };
            match opened(fd) {
                Ok(file) => {
                    prepared = Some((filename, file));
                    break;
                }
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
                Err(error) => return Err(StoreError::io(&self.path(index), error)),
            }
        }
        let (temporary, file) = prepared.ok_or(StoreError::InvalidSlot(
            "segment temporary-name budget exhausted",
        ))?;
        let result = (|| -> StoreResult<()> {
            file.set_len(self.capacity)
                .and_then(|()| file.sync_all())
                .map_err(|e| StoreError::io(&self.path(index), e))?;
            self.check_directory()?;
            // Link the held inode, never a replaceable temporary pathname. /proc
            // names our own open descriptor; no user symlink is followed here.
            let source = CString::new(format!("/proc/self/fd/{}", file.as_raw_fd())).unwrap();
            let target = self.filename(index);
            if unsafe {
                libc::linkat(
                    libc::AT_FDCWD,
                    source.as_ptr(),
                    self.handle.as_raw_fd(),
                    target.as_ptr(),
                    libc::AT_SYMLINK_FOLLOW,
                )
            } < 0
            {
                let error = io::Error::last_os_error();
                if error.kind() != io::ErrorKind::AlreadyExists {
                    return Err(StoreError::io(&self.path(index), error));
                }
            }
            self.handle
                .sync_all()
                .map_err(|e| StoreError::io(&self.directory, e))?;
            Ok(())
        })();
        unsafe {
            libc::unlinkat(self.handle.as_raw_fd(), temporary.as_ptr(), 0);
        }
        if result.is_ok() {
            self.handle
                .sync_all()
                .map_err(|e| StoreError::io(&self.directory, e))?;
        }
        result
    }
    pub fn open(&self, index: u64, write: bool) -> StoreResult<Option<File>> {
        self.check_directory()?;
        let filename = self.filename(index);
        let file = match self.open_named(&filename, write) {
            Ok(file) => file,
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                if !write {
                    self.check_directory()?;
                    return Ok(None);
                }
                self.publish(index)?;
                self.open_named(&filename, true)
                    .map_err(|e| StoreError::io(&self.path(index), e))?
            }
            Err(error) => return Err(StoreError::io(&self.path(index), error)),
        };
        self.check_file(index, &file)?;
        Ok(Some(file))
    }
    pub fn read(&self, index: u64, file: &File, offset: u64, bytes: &mut [u8]) -> StoreResult<()> {
        self.check_file(index, file)?;
        file.read_exact_at(bytes, offset)
            .map_err(|e| StoreError::io(&self.path(index), e))
    }
    pub fn write(&self, index: u64, file: &File, offset: u64, bytes: &[u8]) -> StoreResult<()> {
        self.check_file(index, file)?;
        file.write_all_at(bytes, offset)
            .map_err(|e| StoreError::io(&self.path(index), e))
    }
    pub fn sync(&self, index: u64) -> StoreResult<()> {
        let file = self.open(index, false)?.ok_or_else(|| {
            StoreError::io(
                &self.path(index),
                io::Error::new(io::ErrorKind::NotFound, "dirty segment disappeared"),
            )
        })?;
        file.sync_all()
            .map_err(|e| StoreError::io(&self.path(index), e))
    }
    pub fn bytes_on_disk(&self) -> StoreResult<u64> {
        self.check_directory()?;
        let mut total = 0u64;
        for entry in std::fs::read_dir(format!("/proc/self/fd/{}", self.handle.as_raw_fd()))
            .map_err(|e| StoreError::io(&self.directory, e))?
        {
            let entry = entry.map_err(|e| StoreError::io(&self.directory, e))?;
            let name = entry.file_name();
            let Some(name) = name.to_str() else { continue };
            if name.starts_with(&format!("{}.", self.space)) && name.ends_with(".vec") {
                let path = self.directory.join(entry.file_name());
                let filename = component_name(entry.file_name().as_os_str())
                    .map_err(|e| StoreError::io(&path, e))?;
                let file = self
                    .open_named(&filename, false)
                    .map_err(|e| StoreError::io(&path, e))?;
                let bytes = file
                    .metadata()
                    .map_err(|e| StoreError::io(&path, e))?
                    .blocks()
                    .checked_mul(512)
                    .ok_or(StoreError::InvalidSlot("allocated block size overflows"))?;
                total = total
                    .checked_add(bytes)
                    .ok_or(StoreError::InvalidSlot("allocated block total overflows"))?;
            }
        }
        self.check_directory()?;
        Ok(total)
    }
    pub fn existing_indices(&self, limit: u64) -> StoreResult<BTreeSet<u64>> {
        self.check_directory()?;
        let mut indices = BTreeSet::new();
        let prefix = format!("{}.", self.space);
        for entry in std::fs::read_dir(format!("/proc/self/fd/{}", self.handle.as_raw_fd()))
            .map_err(|e| StoreError::io(&self.directory, e))?
        {
            let entry = entry.map_err(|e| StoreError::io(&self.directory, e))?;
            let name = entry.file_name();
            let Some(name) = name.to_str() else { continue };
            let Some(index) = name
                .strip_prefix(&prefix)
                .and_then(|s| s.strip_suffix(".vec"))
                .and_then(|s| s.parse::<u64>().ok())
            else {
                continue;
            };
            if index < limit && self.path(index).file_name() == Some(entry.file_name().as_os_str())
            {
                indices.insert(index);
            }
        }
        self.check_directory()?;
        Ok(indices)
    }
}

/// Ownership transfer lets a flush work without losing marks made by new writers.
#[derive(Default)]
pub(crate) struct DirtySegments(Mutex<BTreeSet<u64>>);
impl DirtySegments {
    pub fn during_write<T, E>(
        &self,
        index: u64,
        operation: impl FnOnce() -> Result<T, E>,
    ) -> Result<T, E> {
        self.mark(index);
        let result = operation();
        self.mark(index);
        result
    }
    pub fn mark(&self, index: u64) {
        self.0
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .insert(index);
    }
    pub fn take(&self) -> BTreeSet<u64> {
        std::mem::take(&mut *self.0.lock().unwrap_or_else(|e| e.into_inner()))
    }
    pub fn restore(&self, dirty: BTreeSet<u64>) {
        self.0
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .extend(dirty);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn a_write_finishing_after_a_flush_retains_a_new_dirty_mark() {
        // Catches marking only before I/O: fsync can finish before new bytes arrive.
        let dirty = DirtySegments::default();
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("segment");
        let file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&path)
            .unwrap();
        let barrier = std::sync::Barrier::new(2);
        std::thread::scope(|scope| {
            scope.spawn(|| {
                dirty
                    .during_write(0, || {
                        barrier.wait();
                        barrier.wait();
                        file.write_all_at(&[1, 2, 3, 4], 0)
                    })
                    .unwrap();
            });
            barrier.wait();
            assert_eq!(dirty.take(), BTreeSet::from([0]));
            file.sync_all().unwrap();
            barrier.wait();
        });
        assert_eq!(std::fs::read(path).unwrap(), [1, 2, 3, 4]);
        assert_eq!(dirty.take(), BTreeSet::from([0]));
    }
    #[test]
    fn flush_ownership_swap_preserves_marks_made_during_a_flush() {
        let dirty = DirtySegments::default();
        dirty.mark(0);
        let barrier = std::sync::Barrier::new(2);
        std::thread::scope(|scope| {
            scope.spawn(|| {
                let flushing = dirty.take();
                assert_eq!(flushing, BTreeSet::from([0]));
                barrier.wait();
                barrier.wait();
                // A failed fsync must retain both the old and concurrent marks.
                dirty.restore(flushing);
            });
            barrier.wait();
            dirty.mark(0);
            dirty.mark(1);
            barrier.wait();
        });
        assert_eq!(dirty.take(), BTreeSet::from([0, 1]));
        assert!(dirty.take().is_empty());
    }
}
