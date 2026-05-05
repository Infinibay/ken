-- Enable pgvector extension. Schema (tables, indexes) is applied by the
-- engine via sqlx::migrate!() at startup — see crates/engine/migrations/.
CREATE EXTENSION IF NOT EXISTS vector;
