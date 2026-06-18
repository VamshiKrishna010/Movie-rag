-- migrations/004_fts.sql
--
-- Day 4: Adds Postgres full-text search to the `chunks` table for hybrid
-- retrieval. After this runs, every chunk has both a dense vector (existing
-- `embedding` column) AND a sparse keyword index (new `search_vector` column).

-- 1. Generated tsvector column.
--    - to_tsvector('english', text) tokenizes, lowercases, stems, and drops
--      stopwords using English rules. "Films about ISOLATION" becomes the
--      lexeme set {film, isol}.
--    - GENERATED ALWAYS AS (...) STORED means Postgres auto-computes this
--      on every insert/update and stores it on disk. No triggers needed,
--      no risk of `content` and `search_vector` drifting out of sync.
ALTER TABLE chunks
    ADD COLUMN search_vector tsvector
    GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;

-- 2. GIN index on the new column.
--    GIN ("Generalized Inverted iNdex") is the FTS equivalent of ivfflat
--    for vectors: it maps each lexeme back to the row IDs containing it.
--    Without it, every keyword query scans every row.
--    Created AFTER the column is populated, same pattern as ivfflat — bulk
--    work first, index second, since indexing during writes is slower.
CREATE INDEX IF NOT EXISTS chunks_search_vector_idx
    ON chunks USING GIN (search_vector);