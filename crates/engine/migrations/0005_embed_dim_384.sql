-- Switch embedding columns from vector(768) to vector(384).
--
-- The default embedder was nomic-embed-text-v1.5 (quantized) at 768 dims, which
-- pinned ~280 MB resident on first inference and was too heavy on small dev
-- machines. We move to AllMiniLML6V2Q (the same model infinidev uses) at 384
-- dims — ~3× smaller on disk per row, ~5–10× faster on CPU.
--
-- The two embedding spaces are unrelated, so existing vectors cannot be
-- preserved across the dim change. We NULL them and require re-ingest. The
-- schema is hard-coded to 384 from this migration on; switching back to a
-- 768-dim model would require another migration plus a fresh ingest.

DROP INDEX IF EXISTS idx_chunks_embedding;
DROP INDEX IF EXISTS idx_entities_embedding;
DROP INDEX IF EXISTS idx_session_contexts_embedding;

ALTER TABLE chunks            ALTER COLUMN embedding TYPE vector(384) USING NULL;
ALTER TABLE entities          ALTER COLUMN embedding TYPE vector(384) USING NULL;
ALTER TABLE session_contexts  ALTER COLUMN embedding TYPE vector(384) USING NULL;

CREATE INDEX idx_chunks_embedding
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 24, ef_construction = 128)
    WHERE embedding IS NOT NULL;

CREATE INDEX idx_entities_embedding
    ON entities USING hnsw (embedding vector_cosine_ops)
    WITH (m = 24, ef_construction = 128)
    WHERE embedding IS NOT NULL;

CREATE INDEX idx_session_contexts_embedding
    ON session_contexts USING hnsw (embedding vector_cosine_ops)
    WITH (m = 24, ef_construction = 128)
    WHERE embedding IS NOT NULL;
