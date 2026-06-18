CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE movies (
  id            INTEGER PRIMARY KEY,        -- TMDB id
  title         TEXT NOT NULL,
  release_year  INTEGER,
  overview      TEXT,
  tagline       TEXT,
  runtime       INTEGER,
  vote_average  REAL,
  raw           JSONB                       -- keep the original
);
CREATE INDEX movies_title_trgm ON movies USING gin (title gin_trgm_ops);

CREATE TABLE people (
  id    INTEGER PRIMARY KEY,
  name  TEXT NOT NULL
);
CREATE INDEX people_name_trgm ON people USING gin (name gin_trgm_ops);

CREATE TABLE movie_people (
  movie_id   INTEGER REFERENCES movies(id) ON DELETE CASCADE,
  person_id  INTEGER REFERENCES people(id) ON DELETE CASCADE,
  role       TEXT NOT NULL,                  -- 'director', 'actor', 'writer'
  cast_order INTEGER,                        -- null for crew
  PRIMARY KEY (movie_id, person_id, role)
);
CREATE INDEX ON movie_people (person_id);
CREATE INDEX ON movie_people (role);
CREATE INDEX movie_people_person_movie_idx ON movie_people (person_id, movie_id);
CREATE INDEX movie_people_person_role_idx ON movie_people (person_id, role);
CREATE INDEX movie_people_movie_person_actor_idx
  ON movie_people (movie_id, person_id) WHERE role = 'actor';

CREATE TABLE genres (
  id    INTEGER PRIMARY KEY,
  name  TEXT NOT NULL
);
CREATE INDEX genres_name_trgm ON genres USING gin (name gin_trgm_ops);

CREATE TABLE movie_genres (
  movie_id  INTEGER REFERENCES movies(id) ON DELETE CASCADE,
  genre_id  INTEGER REFERENCES genres(id) ON DELETE CASCADE,
  PRIMARY KEY (movie_id, genre_id)
);
CREATE INDEX movie_genres_genre_movie_idx ON movie_genres (genre_id, movie_id);
CREATE INDEX movie_genres_movie_idx ON movie_genres (movie_id);

CREATE TABLE keywords (
  id    INTEGER PRIMARY KEY,
  name  TEXT NOT NULL
);
CREATE INDEX keywords_name_trgm ON keywords USING gin (name gin_trgm_ops);

CREATE TABLE movie_keywords (
  movie_id    INTEGER REFERENCES movies(id) ON DELETE CASCADE,
  keyword_id  INTEGER REFERENCES keywords(id) ON DELETE CASCADE,
  PRIMARY KEY (movie_id, keyword_id)
);
CREATE INDEX movie_keywords_keyword_movie_idx ON movie_keywords (keyword_id, movie_id);
CREATE INDEX movie_keywords_movie_idx ON movie_keywords (movie_id);

CREATE TABLE chunks (
  id          SERIAL PRIMARY KEY,
  movie_id    INTEGER REFERENCES movies(id) ON DELETE CASCADE,
  chunk_type  TEXT NOT NULL,                 -- 'full', 'overview', 'cast', etc.
  content     TEXT NOT NULL,
  embedding   vector(384),
  tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);
CREATE INDEX chunks_movie_idx ON chunks (movie_id);
CREATE INDEX chunks_tsv_idx ON chunks USING GIN (tsv);
-- ivfflat index added AFTER ingestion (needs data to train)
