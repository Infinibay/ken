//! Optional Torch module: no Torch dependency is added to the host workspace.
mod abi;
mod config;
pub mod device;
mod model;
mod output;
mod parameter_file;
mod parameter_zip;
pub mod qwen3;
pub mod weights;
pub mod xlm_roberta;
pub mod xlm_roberta_weights;
pub use abi::ken_model_api_v1;
pub use config::CoreConfig;

#[derive(Debug, thiserror::Error)]
pub enum CoreError {
    #[error("invalid native transformer: {0}")]
    Invalid(String),
    #[error("native tensor operation: {0}")]
    Tensor(#[from] tch::TchError),
    #[error("native model data: {0}")]
    Io(#[from] std::io::Error),
    #[error("native model configuration: {0}")]
    Json(#[from] serde_json::Error),
}

pub(crate) fn invalid(message: impl Into<String>) -> CoreError {
    CoreError::Invalid(message.into())
}
