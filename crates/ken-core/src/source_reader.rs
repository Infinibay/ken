//! Read and stat the same confined, regular source handle.
use crate::project::ProjectPaths;
use std::{
    fs::{self, File, Metadata},
    io::{self, Read},
    path::Path,
};
pub struct SourceFileReader {
    paths: ProjectPaths,
    root: File,
}
pub struct SourceFile {
    file: File,
}
impl SourceFileReader {
    pub fn new(paths: &ProjectPaths) -> io::Result<Self> {
        Ok(Self {
            paths: paths.clone(),
            root: crate::source_handles::open_root(paths.root())?,
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
        let file = crate::source_handles::open(&self.root, relative, false)?;
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
    pub fn read(mut self) -> io::Result<Vec<u8>> {
        let mut bytes = Vec::new();
        self.file.read_to_end(&mut bytes)?;
        Ok(bytes)
    }
}
