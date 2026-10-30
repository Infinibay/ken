//! Authenticated immutable releases and a single owned activation pointer.
mod model;
mod prefix;
mod verify;
pub use model::{PackageEvent, PackageInfo, PackageReport, PackageStatus};
pub use prefix::PackageApplication;
#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("invalid native package: {0}")]
    Invalid(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}
pub type Result<T> = std::result::Result<T, Error>;
fn invalid(message: impl Into<String>) -> Error {
    Error::Invalid(message.into())
}
