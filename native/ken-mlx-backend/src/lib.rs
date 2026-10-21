//! Optional MLX module. The host links no tensor runtime.
pub mod device;
#[derive(Debug, thiserror::Error)]
pub enum CoreError {
    #[error("invalid native MLX model: {0}")]
    Invalid(String),
    #[error("MLX tensor operation: {0}")]
    Tensor(#[from] mlx_rs::error::Exception),
    #[error("MLX parameter archive: {0}")]
    Archive(#[from] mlx_rs::error::IoError),
    #[error("native model data: {0}")]
    Io(#[from] std::io::Error),
    #[error("native model configuration: {0}")]
    Json(#[from] serde_json::Error),
    #[error("native model contract: {0}")]
    Contract(#[from] ken_native_model_api::ApiError),
}
pub(crate) fn invalid(message: impl Into<String>) -> CoreError {
    CoreError::Invalid(message.into())
}

pub mod qwen3;
pub mod weights;

mod abi;
mod model;
mod output;
pub use abi::ken_model_api_v1;
