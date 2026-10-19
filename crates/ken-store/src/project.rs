use crate::{ProjectDatabase, StoreError, StoreResult, VectorSpace, VectorStore, recovery};
use ken_core::project::ProjectPaths;

/// Opens and recovers one explicit project before any database or vectors escape.
pub struct ProjectStore {
    paths: ProjectPaths,
    database: ProjectDatabase,
}
impl ProjectStore {
    pub fn open(paths: &ProjectPaths) -> StoreResult<Self> {
        let db_path = paths.db();
        let parent = db_path
            .parent()
            .ok_or(StoreError::InvalidSlot("database has no parent"))?;
        std::fs::create_dir_all(parent).map_err(|e| StoreError::io(parent, e))?;
        let mut database = ProjectDatabase::open(&db_path)?;
        recovery::recover(&mut database, &paths.vectors())?;
        Ok(Self {
            paths: paths.clone(),
            database,
        })
    }
    pub fn database(&self) -> &ProjectDatabase {
        &self.database
    }
    pub fn database_mut(&mut self) -> &mut ProjectDatabase {
        &mut self.database
    }
    pub fn initialize(&mut self) -> StoreResult<()> {
        self.database.initialize()
    }
    pub fn vectors(
        &self,
        space: VectorSpace,
        dim: usize,
        model: Option<&str>,
    ) -> StoreResult<VectorStore> {
        VectorStore::open(&self.paths.vectors(), space, dim, model)
    }
    pub(crate) fn vector_directory(&self) -> std::path::PathBuf {
        self.paths.vectors()
    }
}
