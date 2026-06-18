import psycopg
from psycopg.rows import dict_row


CHUNK_QUERY = """
SELECT
    m.id,
    m.title,
    m.release_year,
    m.overview,
    m.tagline,
    -- Directors
    (
        SELECT array_agg(p.name ORDER BY p.name)
        FROM movie_people mp
        JOIN people p ON p.id = mp.person_id
        WHERE mp.movie_id = m.id AND mp.role = 'director'
    ) AS directors,
    -- Writers
    (
        SELECT array_agg(p.name ORDER BY p.name)
        FROM movie_people mp
        JOIN people p ON p.id = mp.person_id
        WHERE mp.movie_id = m.id AND mp.role = 'writer'
    ) AS writers,
    -- Top cast (ordered by billing)
    (
        SELECT array_agg(p.name ORDER BY mp.cast_order NULLS LAST)
        FROM movie_people mp
        JOIN people p ON p.id = mp.person_id
        WHERE mp.movie_id = m.id AND mp.role = 'actor'
    ) AS cast_list,
    -- Genres
    (
        SELECT array_agg(g.name ORDER BY g.name)
        FROM movie_genres mg
        JOIN genres g ON g.id = mg.genre_id
        WHERE mg.movie_id = m.id
    ) AS genres,
    -- Keywords
    (
        SELECT array_agg(k.name ORDER BY k.name)
        FROM movie_keywords mk
        JOIN keywords k ON k.id = mk.keyword_id
        WHERE mk.movie_id = m.id
    ) AS keywords
FROM movies m
ORDER BY m.id;
"""

CHUNK_QUERY_MISSING = """
SELECT
    m.id,
    m.title,
    m.release_year,
    m.overview,
    m.tagline,
    (
        SELECT array_agg(p.name ORDER BY p.name)
        FROM movie_people mp
        JOIN people p ON p.id = mp.person_id
        WHERE mp.movie_id = m.id AND mp.role = 'director'
    ) AS directors,
    (
        SELECT array_agg(p.name ORDER BY p.name)
        FROM movie_people mp
        JOIN people p ON p.id = mp.person_id
        WHERE mp.movie_id = m.id AND mp.role = 'writer'
    ) AS writers,
    (
        SELECT array_agg(p.name ORDER BY mp.cast_order NULLS LAST)
        FROM movie_people mp
        JOIN people p ON p.id = mp.person_id
        WHERE mp.movie_id = m.id AND mp.role = 'actor'
    ) AS cast_list,
    (
        SELECT array_agg(g.name ORDER BY g.name)
        FROM movie_genres mg
        JOIN genres g ON g.id = mg.genre_id
        WHERE mg.movie_id = m.id
    ) AS genres,
    (
        SELECT array_agg(k.name ORDER BY k.name)
        FROM movie_keywords mk
        JOIN keywords k ON k.id = mk.keyword_id
        WHERE mk.movie_id = m.id
    ) AS keywords
FROM movies m
WHERE NOT EXISTS (
    SELECT 1 FROM chunks c
    WHERE c.movie_id = m.id AND c.chunk_type = 'full'
)
ORDER BY m.id;
"""


def _join(items: list[str] | None, limit: int | None = None) -> str:
    """Comma-separate a list, optionally capping length."""
    if not items:
        return ""
    if limit:
        items = items[:limit]
    return ", ".join(items)


def _format_movie(row: dict) -> str:
    """Build the rich text chunk for one movie."""
    parts = []

    # Title + year
    year_str = f" ({row['release_year']})" if row["release_year"] else ""
    parts.append(f"{row['title']}{year_str}.")

    # Directors
    directors = _join(row["directors"])
    if directors:
        parts.append(f"Directed by {directors}.")

    # Writers (limit 3 — long writer lists are noise)
    writers = _join(row["writers"], limit=3)
    if writers:
        parts.append(f"Written by {writers}.")

    # Cast (top 5 by billing order)
    cast = _join(row["cast_list"], limit=5)
    if cast:
        parts.append(f"Starring {cast}.")

    # Genres
    genres = _join(row["genres"])
    if genres:
        parts.append(f"Genres: {genres}.")

    # Tagline
    if row["tagline"]:
        parts.append(f"Tagline: {row['tagline']}")

    # Overview (the meat)
    if row["overview"]:
        parts.append(row["overview"])

    # Keywords
    keywords = _join(row["keywords"])
    if keywords:
        parts.append(f"Keywords: {keywords}.")

    return " ".join(parts)


async def build_chunks(conn: psycopg.AsyncConnection) -> list[tuple[int, str]]:
    """Returns [(movie_id, chunk_text), ...] for every movie in the DB."""
    return await _run_chunk_query(conn, CHUNK_QUERY)


async def build_chunks_missing(conn: psycopg.AsyncConnection) -> list[tuple[int, str]]:
    """Returns chunks only for movies that have no ``full`` chunk yet."""
    return await _run_chunk_query(conn, CHUNK_QUERY_MISSING)


async def _run_chunk_query(conn: psycopg.AsyncConnection, sql: str) -> list[tuple[int, str]]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql)
        rows = await cur.fetchall()
    return [(row["id"], _format_movie(row)) for row in rows]