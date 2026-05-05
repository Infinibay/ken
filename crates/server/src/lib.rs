//! HTTP server for context-ai-engine.
//!
//! Routes are wired in `routes.rs`; the public entrypoint is
//! [`build_router`], which returns an `axum::Router` that the binary
//! mounts on a TCP listener and that integration tests drive directly via
//! `tower::ServiceExt`.

pub mod error;
pub mod routes;
pub mod state;

pub use error::ApiError;
pub use state::AppState;

use axum::Router;
use std::sync::Arc;

pub fn build_router(state: Arc<AppState>) -> Router {
    routes::router().with_state(state)
}
