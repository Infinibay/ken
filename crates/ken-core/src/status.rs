//! Read-only state reporting. Transport is supplied through HealthProbe.
mod model;
mod reader;
pub mod rules;
use crate::project::{ProjectError, ProjectPaths};
pub use model::*;
pub use reader::read_status;
use serde_json::{Map, Value};
use std::{io, path::PathBuf};
use thiserror::Error;

pub trait HealthProbe {
    fn probe(
        &self,
        paths: &ProjectPaths,
        metadata: &Map<String, Value>,
    ) -> Result<Option<Map<String, Value>>, StatusError>;
}
#[derive(Debug, Error)]
pub enum StatusError {
    #[error(transparent)]
    Project(#[from] ProjectError),
    #[error("cannot read {path}: {source}")]
    File {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    #[error("invalid metadata at {path}: {reason}")]
    Metadata { path: PathBuf, reason: &'static str },
    #[error("invalid JSON metadata at {path}: {source}")]
    Json {
        path: PathBuf,
        #[source]
        source: serde_json::Error,
    },
    #[error("cannot read SQLite database {path}: {source}")]
    Database {
        path: PathBuf,
        #[source]
        source: rusqlite::Error,
    },
}
