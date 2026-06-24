-- migrations/011_drop_redundant_tsv.sql
--
-- Drops the redundant `tsv` column on `chunks`. The base schema
-- (sql/01_schema.sql) created `tsv`, and migration 004_fts.sql later added an
-- identical generated tsvector column `search_vector` (same expression, its own
-- GIN index). The retriever (app/rag/retriever.py) queries only `search_vector`;
-- `tsv` is unused by code and just doubles storage + write amplification on the
-- chunks table. Idempotent — safe whether or not `tsv` is present.

DROP INDEX IF EXISTS chunks_tsv_idx;
ALTER TABLE chunks DROP COLUMN IF EXISTS tsv;
