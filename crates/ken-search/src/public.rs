//! Shared public search setup and actionable preparation responses.
use crate::{BestSearch, SearchError, SearchInstallation};
use ken_core::project::{DiscoveryContext, ProjectError, ProjectPaths, locate_project};
use ken_index::IndexError;
use ken_models::ModelError;
use ken_retrieval::{RetrievalError, compact, presentation::SearchResponse, query::SearchRequest};
use ken_store::{ProjectDatabase, StoreError};
use serde::Serialize;
use std::{
    fs, io,
    os::unix::fs::MetadataExt,
    path::{Path, PathBuf},
};

#[derive(Debug, thiserror::Error)]
pub enum ApplicationError {
    #[error("error: no .ken project at {0}")]
    MissingProject(PathBuf),
    #[error(transparent)]
    Project(#[from] ProjectError),
    #[error(transparent)]
    Store(#[from] StoreError),
    #[error(transparent)]
    Search(#[from] SearchError),
    #[error("cannot inspect project database {path}: {source}")]
    DatabaseIo { path: PathBuf, source: io::Error },
    #[error("project database changed while opening {0}; retry the search")]
    DatabaseChanged(PathBuf),
}

#[derive(PartialEq, Eq)]
struct DatabaseBinding {
    path: PathBuf,
    device: u64,
    inode: u64,
}
impl DatabaseBinding {
    fn read(paths: &ProjectPaths) -> Result<Self, ApplicationError> {
        let path = paths.db();
        let metadata = fs::metadata(&path).map_err(|source| ApplicationError::DatabaseIo {
            path: path.clone(),
            source,
        })?;
        Ok(Self {
            path,
            device: metadata.dev(),
            inode: metadata.ino(),
        })
    }
}

pub fn resolve_index(
    path: &Path,
    context: &DiscoveryContext,
) -> Result<ProjectPaths, ApplicationError> {
    let paths = match locate_project(path, context)? {
        Some(paths) => paths,
        None => ProjectPaths::at(path, context)?,
    };
    if !paths.db().is_file() {
        return Err(ApplicationError::MissingProject(paths.root().into()));
    }
    Ok(paths)
}

#[derive(Serialize)]
pub struct PreparationFailure {
    ok: bool,
    code: &'static str,
    error: String,
    next_action: &'static str,
    results: [(); 0],
}
#[derive(Serialize)]
#[serde(untagged)]
pub enum PublicSearchResponse {
    Matches(SearchResponse),
    PreparationRequired(PreparationFailure),
}
impl PublicSearchResponse {
    fn preparation(error: impl ToString) -> Self {
        Self::PreparationRequired(PreparationFailure {
            ok: false,
            code: "search_preparation_required",
            error: error.to_string(),
            next_action: "Run ken retrieval prepare --path PROJECT, then retry.",
            results: [],
        })
    }
    pub fn is_success(&self) -> bool {
        matches!(self, Self::Matches(_))
    }
    pub fn render(&self, diagnostics: bool) -> String {
        match self {
            Self::Matches(response) => compact::render(response, diagnostics),
            Self::PreparationRequired(error) => format!("{}\n{}", error.error, error.next_action),
        }
    }
}

fn preparation_error(error: &SearchError) -> bool {
    let retrieval = match error {
        SearchError::Retrieval(error) | SearchError::Index(IndexError::Retrieval(error)) => error,
        _ => return false,
    };
    matches!(
        retrieval,
        RetrievalError::Version(_) | RetrievalError::Model(ModelError::Io { .. })
    )
}

/// Retain one registered engine across CLI/MCP requests; installation failures retry.
pub struct SearchApplication {
    installation: PathBuf,
    engine: Option<BestSearch>,
    database: Option<DatabaseBinding>,
}
impl SearchApplication {
    pub fn new(installation: PathBuf) -> Self {
        Self {
            installation,
            engine: None,
            database: None,
        }
    }
    pub fn find(
        &mut self,
        paths: &ProjectPaths,
        request: &SearchRequest,
    ) -> Result<PublicSearchResponse, ApplicationError> {
        if !paths.db().is_file() {
            return Err(ApplicationError::MissingProject(paths.root().into()));
        }
        let binding = DatabaseBinding::read(paths)?;
        let mut db = ProjectDatabase::open(&paths.db())?;
        if binding != DatabaseBinding::read(paths)? {
            return Err(ApplicationError::DatabaseChanged(paths.db()));
        }
        if self.engine.is_none() {
            match SearchInstallation::open(&self.installation) {
                Ok(installation) => self.engine = Some(installation.into_search()),
                Err(error) => return Ok(PublicSearchResponse::preparation(error)),
            }
        }
        let engine = self.engine.as_mut().expect("initialized search engine");
        if self.database.as_ref() != Some(&binding) {
            // A replacement can reuse both its pathname and retrieval generation.
            // Keep authenticated model owners while discarding source-bound state.
            engine.invalidate_projects();
            self.database = Some(binding);
        }
        match engine.search(&mut db, paths, request) {
            Ok(response) => Ok(PublicSearchResponse::Matches(response)),
            Err(error) if preparation_error(&error) => Ok(PublicSearchResponse::preparation(error)),
            Err(error) => Err(error.into()),
        }
    }
}
