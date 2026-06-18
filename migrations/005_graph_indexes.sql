-- migrations/005_graph_indexes.sql
--
-- Composite indexes for graph traversal queries in app/graph/queries.py.
-- Run after ingestion for best build performance (same pattern as ivfflat).

-- person → movies (filmography, intersection)
CREATE INDEX IF NOT EXISTS movie_people_person_movie_idx
    ON movie_people (person_id, movie_id);

CREATE INDEX IF NOT EXISTS movie_people_person_role_idx
    ON movie_people (person_id, role);

-- movie → co-stars (path BFS reverse hop)
CREATE INDEX IF NOT EXISTS movie_people_movie_person_actor_idx
    ON movie_people (movie_id, person_id)
    WHERE role = 'actor';

-- entity → movies (shared-entity similarity)
CREATE INDEX IF NOT EXISTS movie_keywords_keyword_movie_idx
    ON movie_keywords (keyword_id, movie_id);

CREATE INDEX IF NOT EXISTS movie_genres_genre_movie_idx
    ON movie_genres (genre_id, movie_id);

-- movie → entities (source movie lookup)
CREATE INDEX IF NOT EXISTS movie_keywords_movie_idx
    ON movie_keywords (movie_id);

CREATE INDEX IF NOT EXISTS movie_genres_movie_idx
    ON movie_genres (movie_id);
