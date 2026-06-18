-- migrations/006_pg_trgm.sql
--
-- Entity extraction for graph retrieval (app/graph/entities.py) uses pg_trgm
-- similarity() and the %% trigram operator for fuzzy name matching.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS people_name_trgm
    ON people USING gin (name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS movies_title_trgm
    ON movies USING gin (title gin_trgm_ops);

CREATE INDEX IF NOT EXISTS genres_name_trgm
    ON genres USING gin (name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS keywords_name_trgm
    ON keywords USING gin (name gin_trgm_ops);
