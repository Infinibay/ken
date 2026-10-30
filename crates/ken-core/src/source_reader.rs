//! Read and stat the same confined, regular source handle.
use crate::project::ProjectPaths;
use std::{
    fs::{self, File, Metadata},
    io::{self, Read},
    path::Path,
};
/// Hold a canonical directory without following a replacement symlink.
pub fn open_directory(path: &Path) -> io::Result<File> {
    crate::source_handles::open_root(path)
}
/// Open a confined component path relative to an already held directory.
pub fn open_relative(root: &File, relative: &Path, directory: bool) -> io::Result<File> {
    crate::source_handles::open(root, relative, directory)
}
pub struct SourceFileReader {
    paths: ProjectPaths,
}
pub struct SourceFile {
    file: File,
}
impl SourceFileReader {
    pub fn new(paths: &ProjectPaths) -> io::Result<Self> {
        crate::source_handles::open_root(paths.root())?;
        Ok(Self {
            paths: paths.clone(),
        })
    }
    pub fn open(&self, path: &Path) -> io::Result<SourceFile> {
        let canonical = fs::canonicalize(self.paths.root().join(path))?;
        let relative = canonical.strip_prefix(self.paths.root()).map_err(|_| {
            io::Error::new(
                io::ErrorKind::PermissionDenied,
                "source path escapes project root",
            )
        })?;
        // Bind each new read to the current root name. A previously opened
        // source retains its own handle, but a renamed root is not a snapshot
        // for future reads (which must detect changed source hashes).
        let root = crate::source_handles::open_root(self.paths.root())?;
        let file = crate::source_handles::open(&root, relative, false)?;
        if !file.metadata()?.is_file() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "source is not a regular file",
            ));
        }
        Ok(SourceFile { file })
    }
}
impl SourceFile {
    pub fn metadata(&self) -> io::Result<Metadata> {
        self.file.metadata()
    }
    /// Bound bytes from the same source handle, including growth after stat.
    /// None means the file exceeded the caller's explicit limit.
    pub fn read_bounded(self, limit: u64) -> io::Result<Option<Vec<u8>>> {
        self.read_bounded_checked(limit, &mut || Ok(()))
    }
    /// Cooperative bounded reads keep source bytes and stat on the same held handle.
    pub fn read_bounded_checked<E: From<io::Error>>(
        self,
        limit: u64,
        check: &mut dyn FnMut() -> Result<(), E>,
    ) -> Result<Option<Vec<u8>>, E> {
        check()?;
        let mut reader = self.file.take(limit.saturating_add(1));
        let mut bytes = Vec::new();
        let mut chunk = [0u8; 8192];
        loop {
            check()?;
            let size = reader.read(&mut chunk)?;
            if size == 0 {
                break;
            }
            bytes.extend_from_slice(&chunk[..size]);
        }
        check()?;
        Ok((bytes.len() as u64 <= limit).then_some(bytes))
    }
    pub fn read(mut self) -> io::Result<Vec<u8>> {
        let mut bytes = Vec::new();
        self.file.read_to_end(&mut bytes)?;
        Ok(bytes)
    }
}
