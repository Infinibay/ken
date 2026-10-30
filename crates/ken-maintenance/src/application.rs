use crate::{Error, Result};
use ken_core::project::ProjectPaths;
use ken_store::ProjectStore;
use std::path::Path;
pub struct MaintenanceApplication {
    pub(crate) paths: ProjectPaths,
    pub(crate) store: ProjectStore,
}
impl MaintenanceApplication {
    pub fn open(root: &Path) -> Result<Self> {
        let paths = crate::paths(root)?;
        if !paths.root().is_dir() || !paths.db().is_file() {
            return Err(Error::Invalid(format!(
                "no ken index at {}",
                paths.root().display()
            )));
        }
        let mut store = ProjectStore::open(&paths)?;
        store.initialize()?;
        Ok(Self { paths, store })
    }
    pub fn database(&self) -> &ken_store::ProjectDatabase {
        self.store.database()
    }
    pub fn root(&self) -> &Path {
        self.paths.root()
    }
}
