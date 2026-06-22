-- migrations/005_graph_indexes.sql
--
-- Composite indexes for relational movie metadata lookups.
-- Run after ingestion for best build performance (same pattern as ivfflat).

-- person → movies
CREATE INDEX IF NOT EXISTS movie_people_person_movie_idx
    ON movie_people (person_id, movie_id);

CREATE INDEX IF NOT EXISTS movie_people_person_role_idx
    ON movie_people (person_id, role);

-- movie → actors
CREATE INDEX IF NOT EXISTS movie_people_movie_person_actor_idx
    ON movie_people (movie_id, person_id)
    WHERE role = 'actor';

-- entity → movies
CREATE INDEX IF NOT EXISTS movie_keywords_keyword_movie_idx
    ON movie_keywords (keyword_id, movie_id);

CREATE INDEX IF NOT EXISTS movie_genres_genre_movie_idx
    ON movie_genres (genre_id, movie_id);

-- movie → entities
CREATE INDEX IF NOT EXISTS movie_keywords_movie_idx
    ON movie_keywords (movie_id);

CREATE INDEX IF NOT EXISTS movie_genres_movie_idx
    ON movie_genres (movie_id);
