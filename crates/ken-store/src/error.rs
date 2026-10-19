use std::path::{Path, PathBuf};
use thiserror::Error;

pub type StoreResult<T> = Result<T, StoreError>;

#[derive(Debug, Error)]
pub enum StoreError {
    #[error("SQLite database {path:?}: {source}")]
    Sqlite {
        path: PathBuf,
        #[source]
        source: rusqlite::Error,
    },
    #[error("invalid vector slot allocation: {0}")]
    InvalidSlot(&'static str),
    #[error("unknown vector space {0:?}")]
    UnknownSpace(String),
}

impl StoreError {
    pub(crate) fn sqlite(path: &Path, source: rusqlite::Error) -> Self {
        Self::Sqlite {
            path: path.into(),
            source,
        }
    }
}

pub(crate) fn sql_error(conn: &rusqlite::Connection, source: rusqlite::Error) -> StoreError {
    StoreError::sqlite(
        Path::new(conn.path().unwrap_or("<SQLite connection>")),
        source,
    )
}
