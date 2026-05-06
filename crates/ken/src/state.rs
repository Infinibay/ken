use std::sync::Arc;

use engine::embed::Embedder;
use engine::postgres::PostgresStorage;

/// Shared state every handler closes over.
///
/// `embedder` is `Arc<dyn Embedder>` so the binary can swap MockEmbedder for
/// fastembed without touching the routes (`#11`).
pub struct AppState {
    pub storage: PostgresStorage,
    pub embedder: Arc<dyn Embedder>,
}
