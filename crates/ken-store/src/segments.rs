//! Fixed file publication and owned positional I/O. No file-backed borrowed slices.
use crate::{StoreError, StoreResult};
use std::{
    collections::BTreeSet,
    fs::{File, OpenOptions},
    io,
    os::unix::fs::{FileExt, MetadataExt},
    path::{Path, PathBuf},
    sync::Mutex,
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

pub(crate) struct Segments {
    pub directory: PathBuf,
    pub space: crate::VectorSpace,
    pub capacity: u64,
}

impl Segments {
    pub fn path(&self, index: u64) -> PathBuf {
        self.directory
            .join(format!("{}.{index:04}.vec", self.space))
    }
    pub fn open(&self, index: u64, write: bool) -> StoreResult<Option<File>> {
        let path = self.path(index);
        if write && !path.try_exists().map_err(|e| StoreError::io(&path, e))? {
            publish_new(&path, |f| f.set_len(self.capacity))?;
        }
        let file = match OpenOptions::new().read(true).write(write).open(&path) {
            Ok(file) => file,
            Err(e) if !write && e.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(e) => return Err(StoreError::io(&path, e)),
        };
        let metadata = file.metadata().map_err(|e| StoreError::io(&path, e))?;
        if !metadata.is_file() || metadata.len() != self.capacity {
            return Err(StoreError::io(
                &path,
                io::Error::new(
                    io::ErrorKind::InvalidData,
                    "segment does not have its full fixed capacity",
                ),
            ));
        }
        Ok(Some(file))
    }
    pub fn read(&self, index: u64, file: &File, offset: u64, bytes: &mut [u8]) -> StoreResult<()> {
        file.read_exact_at(bytes, offset)
            .map_err(|e| StoreError::io(&self.path(index), e))
    }
    pub fn write(&self, index: u64, file: &File, offset: u64, bytes: &[u8]) -> StoreResult<()> {
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
        let mut total = 0u64;
        for entry in
            std::fs::read_dir(&self.directory).map_err(|e| StoreError::io(&self.directory, e))?
        {
            let entry = entry.map_err(|e| StoreError::io(&self.directory, e))?;
            let name = entry.file_name();
            let Some(name) = name.to_str() else { continue };
            if name.starts_with(&format!("{}.", self.space)) && name.ends_with(".vec") {
                let path = entry.path();
                let bytes = std::fs::metadata(&path)
                    .map_err(|e| StoreError::io(&path, e))?
                    .blocks()
                    .checked_mul(512)
                    .ok_or(StoreError::InvalidSlot("allocated block size overflows"))?;
                total = total
                    .checked_add(bytes)
                    .ok_or(StoreError::InvalidSlot("allocated block total overflows"))?;
            }
        }
        Ok(total)
    }
    pub fn existing_indices(&self, limit: u64) -> StoreResult<BTreeSet<u64>> {
        let mut indices = BTreeSet::new();
        let prefix = format!("{}.", self.space);
        for entry in
            std::fs::read_dir(&self.directory).map_err(|e| StoreError::io(&self.directory, e))?
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
