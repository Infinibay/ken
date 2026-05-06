-- Performance pass before any users.
--
-- 1. Bump HNSW build params (m, ef_construction) for higher recall ceiling.
--    Defaults are m=16, ef_construction=64 — ok for tiny corpora, slightly
--    underbuilt for retrieval at top_k=200. m=24, ef_construction=128 is the
--    sweet spot recommended in pgvector docs; values still apply at 384-dim.
-- 2. Add a dedicated partial index on session_contexts(workspace_id, created_at)
--    WHERE embedding IS NOT NULL. The existing idx_session_contexts_ws_time
--    is full-table; the partial variant is what predictive_scores actually
--    needs.
--
-- Per-query `hnsw.ef_search` is set in code (semantic_search_chunks); not
-- a schema-level concern.

DROP INDEX IF EXISTS idx_chunks_embedding;
CREATE INDEX idx_chunks_embedding
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 24, ef_construction = 128)
    WHERE embedding IS NOT NULL;

DROP INDEX IF EXISTS idx_entities_embedding;
CREATE INDEX idx_entities_embedding
    ON entities USING hnsw (embedding vector_cosine_ops)
    WITH (m = 24, ef_construction = 128)
    WHERE embedding IS NOT NULL;

DROP INDEX IF EXISTS idx_session_contexts_embedding;
CREATE INDEX idx_session_contexts_embedding
    ON session_contexts USING hnsw (embedding vector_cosine_ops)
    WITH (m = 24, ef_construction = 128)
    WHERE embedding IS NOT NULL;

CREATE INDEX idx_session_contexts_ws_time_embedded
    ON session_contexts(workspace_id, created_at DESC)
    WHERE embedding IS NOT NULL;

-- Reactive channel orders by `id` (insertion order). Adding a (session_id, id)
-- composite isn't strictly needed since BIGSERIAL ids monotonically increase,
-- but a (session_id, iteration) index becomes useful when reactive starts
-- using an iteration window (the slim-query optimization). Cheap to add now.
CREATE INDEX idx_session_interactions_session_iter
    ON session_interactions(session_id, iteration);
