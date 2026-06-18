-- migrations/007_hnsw.sql
--
-- HNSW index for approximate nearest-neighbor vector search.
-- Run AFTER embed_and_store() has populated chunks.embedding.
-- Much faster than sequential scan at ~1k+ rows; tune m/ef_construction at scale.

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
