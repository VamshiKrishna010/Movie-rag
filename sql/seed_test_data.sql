-- Minimal fixture used by CI so tests/test_movies.py has rows to query.
-- Loaded after sql/01_schema.sql and the user migrations. Idempotent
-- (ON CONFLICT DO NOTHING) so a re-run on an already-seeded DB is a no-op.

INSERT INTO genres (id, name) VALUES
  (28, 'Action'),
  (18, 'Drama'),
  (35, 'Comedy'),
  (53, 'Thriller'),
  (878, 'Science Fiction')
ON CONFLICT (id) DO NOTHING;

INSERT INTO people (id, name) VALUES
  (1, 'Test Director One'),
  (2, 'Test Director Two'),
  (3, 'Test Writer One'),
  (4, 'Test Writer Two'),
  (5, 'Test Actor One'),
  (6, 'Test Actor Two'),
  (7, 'Test Actor Three'),
  (8, 'Test Actor Four')
ON CONFLICT (id) DO NOTHING;

INSERT INTO keywords (id, name) VALUES
  (101, 'space'),
  (102, 'time travel'),
  (103, 'heist'),
  (104, 'friendship'),
  (105, 'dystopia')
ON CONFLICT (id) DO NOTHING;

INSERT INTO movies (id, title, release_year, overview, tagline, runtime, vote_average, raw) VALUES
  (9001, 'Test Movie Alpha',   2021, 'Alpha overview for tests.',   'Alpha tagline',   120, 9.1, '{"poster_path":"/alpha.jpg","backdrop_path":"/alpha_bd.jpg"}'::jsonb),
  (9002, 'Test Movie Beta',    2020, 'Beta overview for tests.',    'Beta tagline',    110, 8.8, '{"poster_path":"/beta.jpg"}'::jsonb),
  (9003, 'Test Movie Gamma',   2019, 'Gamma overview for tests.',   'Gamma tagline',   105, 8.5, '{"poster_path":"/gamma.jpg"}'::jsonb),
  (9004, 'Test Movie Delta',   2018, 'Delta overview for tests.',   'Delta tagline',    98, 8.2, '{"poster_path":"/delta.jpg"}'::jsonb),
  (9005, 'Test Movie Epsilon', 2017, 'Epsilon overview for tests.', 'Epsilon tagline', 115, 7.9, '{"poster_path":"/epsilon.jpg"}'::jsonb),
  (9006, 'Test Movie Zeta',    2016, 'Zeta overview for tests.',    'Zeta tagline',    102, 7.6, '{"poster_path":"/zeta.jpg"}'::jsonb),
  (9007, 'Test Movie Eta',     2015, 'Eta overview for tests.',     'Eta tagline',      99, 7.3, '{"poster_path":"/eta.jpg"}'::jsonb),
  (9008, 'Test Movie Theta',   2014, 'Theta overview for tests.',   'Theta tagline',   108, 7.0, '{"poster_path":"/theta.jpg"}'::jsonb)
ON CONFLICT (id) DO NOTHING;

INSERT INTO movie_genres (movie_id, genre_id) VALUES
  (9001, 28), (9001, 878),
  (9002, 18),
  (9003, 35),
  (9004, 53),
  (9005, 878),
  (9006, 28),
  (9007, 18),
  (9008, 35)
ON CONFLICT DO NOTHING;

INSERT INTO movie_people (movie_id, person_id, role, cast_order) VALUES
  (9001, 1, 'director', NULL),
  (9001, 3, 'writer',   NULL),
  (9001, 5, 'actor',    0),
  (9001, 6, 'actor',    1),
  (9001, 7, 'actor',    2),
  (9001, 8, 'actor',    3),
  (9002, 2, 'director', NULL),
  (9002, 4, 'writer',   NULL),
  (9002, 5, 'actor',    0)
ON CONFLICT DO NOTHING;

INSERT INTO movie_keywords (movie_id, keyword_id) VALUES
  (9001, 101), (9001, 102),
  (9002, 104),
  (9003, 103)
ON CONFLICT DO NOTHING;
