//! Translate the shared filesystem owner's errors at the host policy boundary.
use crate::{Error, Result};
use ken_core::project_files::{self, Lock, ProjectFiles};
pub(crate) use project_files::MAX_BYTES;
use std::path::{Path, PathBuf};
fn error(error: project_files::Error) -> Error {
    match error {
        project_files::Error::Invalid(message) => Error::Invalid(message),
        project_files::Error::Io(error) => Error::Io(error),
    }
}
pub(crate) fn parts(value: &str) -> Result<Vec<&str>> {
    project_files::parts(value).map_err(error)
}
pub(crate) struct Root {
    pub path: PathBuf,
    owner: ProjectFiles,
}
impl Root {
    pub fn new(root: &Path) -> Result<Self> {
        let owner = ProjectFiles::new(root).map_err(error)?;
        Ok(Self {
            path: owner.path.clone(),
            owner,
        })
    }
    pub fn duplicate(&self) -> Result<Self> {
        let owner = self.owner.duplicate().map_err(error)?;
        Ok(Self {
            path: owner.path.clone(),
            owner,
        })
    }
    pub fn lock(&self) -> Result<Lock> {
        self.owner.lock().map_err(error)
    }
    pub fn read(&self, path: &str) -> Result<Option<Vec<u8>>> {
        self.owner.read(path).map_err(error)
    }
    pub fn exists(&self, path: &str) -> Result<bool> {
        self.owner.exists(path).map_err(error)
    }
    pub fn is_file(&self, path: &str) -> Result<bool> {
        self.owner.is_file(path).map_err(error)
    }
    pub fn is_directory(&self, path: &str) -> Result<bool> {
        self.owner.is_directory(path).map_err(error)
    }
    pub fn nonempty_directory(&self, path: &str) -> Result<bool> {
        self.owner.nonempty_directory(path).map_err(error)
    }
    pub fn add_owner_write(&self, path: &str) -> Result<()> {
        self.owner.add_owner_write(path).map_err(error)
    }
    pub fn write(&self, path: &str, bytes: &[u8]) -> Result<()> {
        self.owner.write(path, bytes).map_err(error)
    }
    pub fn remove(&self, path: &str) -> Result<()> {
        self.owner.remove(path).map_err(error)
    }
    pub fn prune(&self, path: &str, boundary: &str) {
        self.owner.prune(path, boundary)
    }
}
