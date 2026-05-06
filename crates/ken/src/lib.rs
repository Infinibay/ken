//! `ken` — context engine for coding agents. Exposes both the HTTP server
//! (axum) and the agent-facing pieces (MCP stdio server, install-into-Claude
//! Code helper, hook handlers) as one library crate so the single `ken`
//! binary can dispatch to any of them.

pub mod client;
pub mod error;
pub mod hook;
pub mod install;
pub mod mcp;
pub mod routes;
pub mod state;
pub mod url_crawl;

pub use error::ApiError;
pub use state::AppState;

use axum::Router;
use std::sync::Arc;

pub fn build_router(state: Arc<AppState>) -> Router {
    routes::router().with_state(state)
}
