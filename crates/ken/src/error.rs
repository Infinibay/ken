use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use engine::ingest::IngestError;
use engine::postgres::PgStorageError;
use engine::storage::StorageError;
use serde_json::json;

/// Translates engine-side errors into JSON HTTP responses. Variants map to
/// status codes via `into_response`; the body is always
/// `{"error": "<message>"}` so callers can rely on a single shape.
#[derive(Debug, thiserror::Error)]
pub enum ApiError {
    #[error("{0}")]
    Storage(#[from] StorageError),

    #[error("{0}")]
    Postgres(#[from] PgStorageError),

    #[error("{0}")]
    Ingest(#[from] IngestError),

    #[error("invalid input: {0}")]
    Invalid(String),

    #[error("not found")]
    NotFound,
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let status = match &self {
            ApiError::NotFound => StatusCode::NOT_FOUND,
            ApiError::Invalid(_) => StatusCode::BAD_REQUEST,
            ApiError::Ingest(_) => StatusCode::BAD_REQUEST,
            ApiError::Storage(StorageError::TenantNotFound(_))
            | ApiError::Storage(StorageError::WorkspaceNotFound(_))
            | ApiError::Storage(StorageError::SourceNotFound(_))
            | ApiError::Storage(StorageError::DocumentNotFound(_))
            | ApiError::Storage(StorageError::ChunkNotFound(_))
            | ApiError::Storage(StorageError::EntityNotFound(_))
            | ApiError::Storage(StorageError::SessionNotFound(_))
            | ApiError::Storage(StorageError::ContextNotFound(_))
            | ApiError::Storage(StorageError::InteractionNotFound(_)) => StatusCode::NOT_FOUND,
            ApiError::Storage(StorageError::Invalid(_)) => StatusCode::BAD_REQUEST,
            ApiError::Postgres(_) => StatusCode::INTERNAL_SERVER_ERROR,
        };
        (status, Json(json!({ "error": self.to_string() }))).into_response()
    }
}

pub type ApiResult<T> = Result<T, ApiError>;
