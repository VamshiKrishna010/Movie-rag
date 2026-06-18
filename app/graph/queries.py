# app/graph/queries.py
"""
Graph traversal queries over the movie schema.

Mental model: every join table is a set of edges.
    movie_people  : (Person) --{role}--> (Movie)
    movie_genres  : (Movie)  --HAS_GENRE--> (Genre)
    movie_keywords: (Movie)  --HAS_KEYWORD--> (Keyword)

Each function below answers ONE shape of relational question.
All return (movie_id, score) so the retriever can rank and merge with
vector/FTS results downstream.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import psycopg
from psycopg.rows import dict_row

Role = Literal["actor", "director", "writer", "producer", "any"]

# Ingest stores actor / director / writer only (see app/ingest/pipeline.py).
_ROLE_FILTER: dict[str, str | None] = {
    "actor": "actor",
    "director": "director",
    "writer": "writer",
    "producer": None,
    "any": None,
}


@dataclass
class GraphHit:
    movie_id: int
    score: float
    reason: str


# ---------------------------------------------------------------------------
# 1. movies_by_person — 1-hop filmography via movie_people
# ---------------------------------------------------------------------------

_SQL_MOVIES_BY_PERSON_ACTOR = """
SELECT
    mp.movie_id,
    1.0 / (1.0 + COALESCE(mp.cast_order, 10) * 0.1) AS score
FROM movie_people mp
WHERE mp.person_id = %(person_id)s AND mp.role = 'actor'
ORDER BY score DESC
LIMIT %(limit)s
"""

_SQL_MOVIES_BY_PERSON_ROLE = """
SELECT mp.movie_id, 1.0 AS score
FROM movie_people mp
WHERE mp.person_id = %(person_id)s AND mp.role = %(role)s
ORDER BY mp.movie_id
LIMIT %(limit)s
"""

_SQL_MOVIES_BY_PERSON_ANY = """
WITH scored AS (
    SELECT mp.movie_id,
           CASE WHEN mp.role = 'actor'
                THEN 1.0 / (1.0 + COALESCE(mp.cast_order, 10) * 0.1)
                ELSE 1.0
           END AS score
    FROM movie_people mp
    WHERE mp.person_id = %(person_id)s
)
SELECT movie_id, MAX(score) AS score
FROM scored
GROUP BY movie_id
ORDER BY score DESC
LIMIT %(limit)s
"""

_REASON_BY_ROLE = {
    "actor": "acted in (person={pid})",
    "director": "directed (person={pid})",
    "writer": "wrote (person={pid})",
    "any": "linked to person={pid}",
}


async def movies_by_person(
    conn: psycopg.AsyncConnection,
    person_id: int,
    role: Role = "any",
    limit: int = 50,
) -> list[GraphHit]:
    """All movies where the given person played the given role."""
    if role != "any" and _ROLE_FILTER.get(role) is None:
        return []

    async with conn.cursor(row_factory=dict_row) as cur:
        if role == "any":
            sql, params = _SQL_MOVIES_BY_PERSON_ANY, {
                "person_id": person_id, "limit": limit,
            }
            reason_tpl = _REASON_BY_ROLE["any"]
        elif role == "actor":
            sql, params = _SQL_MOVIES_BY_PERSON_ACTOR, {
                "person_id": person_id, "limit": limit,
            }
            reason_tpl = _REASON_BY_ROLE["actor"]
        else:
            sql, params = _SQL_MOVIES_BY_PERSON_ROLE, {
                "person_id": person_id,
                "role": _ROLE_FILTER[role],
                "limit": limit,
            }
            reason_tpl = _REASON_BY_ROLE[role]

        await cur.execute(sql, params)
        rows = await cur.fetchall()

    reason = reason_tpl.format(pid=person_id)
    return [GraphHit(r["movie_id"], float(r["score"]), reason) for r in rows]


# ---------------------------------------------------------------------------
# 2. movies_by_people_intersection — strict set intersection
# ---------------------------------------------------------------------------

_SQL_PEOPLE_INTERSECTION_PAIR = """
SELECT DISTINCT a.movie_id, 1.0 AS score
FROM movie_people a
JOIN movie_people b
  ON b.movie_id = a.movie_id AND b.person_id = %(p2)s
WHERE a.person_id = %(p1)s
LIMIT %(limit)s
"""

_SQL_PEOPLE_INTERSECTION = """
WITH person_movies AS (
    SELECT movie_id, person_id
    FROM movie_people
    WHERE person_id = ANY(%(person_ids)s)
)
SELECT
    movie_id,
    COUNT(DISTINCT person_id)::float / %(n_required)s AS score
FROM person_movies
GROUP BY movie_id
HAVING COUNT(DISTINCT person_id) = %(n_required)s
ORDER BY score DESC
LIMIT %(limit)s
"""


async def movies_by_people_intersection(
    conn: psycopg.AsyncConnection,
    person_ids: list[int],
    limit: int = 50,
) -> list[GraphHit]:
    """Movies where EVERY listed person appears in movie_people."""
    if not person_ids:
        return []

    async with conn.cursor(row_factory=dict_row) as cur:
        if len(person_ids) == 2:
            await cur.execute(_SQL_PEOPLE_INTERSECTION_PAIR, {
                "p1": person_ids[0],
                "p2": person_ids[1],
                "limit": limit,
            })
        else:
            await cur.execute(_SQL_PEOPLE_INTERSECTION, {
                "person_ids": person_ids,
                "n_required": len(person_ids),
                "limit": limit,
            })
        rows = await cur.fetchall()

    return [
        GraphHit(
            movie_id=r["movie_id"],
            score=float(r["score"]),
            reason=f"features all {len(person_ids)} requested people",
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# 3. related_movies_by_shared_entities — 2-hop structural similarity
# ---------------------------------------------------------------------------

_SQL_RELATED_BY_SHARED = """
WITH
src_kw AS (
    SELECT keyword_id FROM movie_keywords WHERE movie_id = %(movie_id)s
),
src_gen AS (
    SELECT genre_id FROM movie_genres WHERE movie_id = %(movie_id)s
),
src_cast AS (
    SELECT person_id FROM movie_people
    WHERE movie_id = %(movie_id)s
      AND role = 'actor'
      AND COALESCE(cast_order, 99) < 10
),
candidates AS (
    SELECT mk.movie_id, 'keyword' AS etype
    FROM movie_keywords mk
    WHERE mk.keyword_id IN (SELECT keyword_id FROM src_kw)
      AND mk.movie_id <> %(movie_id)s
    UNION ALL
    SELECT mg.movie_id, 'genre'
    FROM movie_genres mg
    WHERE mg.genre_id IN (SELECT genre_id FROM src_gen)
      AND mg.movie_id <> %(movie_id)s
    UNION ALL
    SELECT mp.movie_id, 'cast'
    FROM movie_people mp
    WHERE mp.person_id IN (SELECT person_id FROM src_cast)
      AND mp.role = 'actor'
      AND mp.movie_id <> %(movie_id)s
      AND COALESCE(mp.cast_order, 99) < 10
)
SELECT
    movie_id,
    LEAST(1.0,
        SUM(CASE etype WHEN 'keyword' THEN 0.5
                       WHEN 'cast'    THEN 0.3
                       WHEN 'genre'   THEN 0.1 END)
        / 5.0
    ) AS score,
    SUM(CASE WHEN etype = 'keyword' THEN 1 ELSE 0 END) AS shared_keywords,
    SUM(CASE WHEN etype = 'cast'    THEN 1 ELSE 0 END) AS shared_cast,
    SUM(CASE WHEN etype = 'genre'   THEN 1 ELSE 0 END) AS shared_genres
FROM candidates
GROUP BY movie_id
ORDER BY score DESC
LIMIT %(limit)s
"""


async def related_movies_by_shared_entities(
    conn: psycopg.AsyncConnection,
    movie_id: int,
    limit: int = 20,
) -> list[GraphHit]:
    """Find movies sharing keywords / top cast / genres with the given one."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_SQL_RELATED_BY_SHARED, {
            "movie_id": movie_id, "limit": limit,
        })
        rows = await cur.fetchall()

    return [
        GraphHit(
            movie_id=r["movie_id"],
            score=float(r["score"]),
            reason=(
                f"shares {r['shared_keywords']} kw, "
                f"{r['shared_cast']} cast, "
                f"{r['shared_genres']} genres with movie={movie_id}"
            ),
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# 4. movies_by_genres_and_keywords — tag overlap filter
# ---------------------------------------------------------------------------

def _build_tags_sql(genre_ids: list[int], keyword_ids: list[int]) -> str:
    """Build tagged CTE from only the branches that have IDs."""
    parts: list[str] = []
    if genre_ids:
        parts.append(
            "SELECT movie_id, 'genre' AS etype FROM movie_genres "
            "WHERE genre_id = ANY(%(genre_ids)s)"
        )
    if keyword_ids:
        parts.append(
            "SELECT movie_id, 'keyword' AS etype FROM movie_keywords "
            "WHERE keyword_id = ANY(%(keyword_ids)s)"
        )
    tagged = " UNION ALL ".join(parts)
    return f"""
WITH tagged AS (
    {tagged}
)
SELECT
    movie_id,
    COUNT(*)::float / %(n_required)s AS score,
    COUNT(*) FILTER (WHERE etype = 'keyword') AS kw_hits,
    COUNT(*) FILTER (WHERE etype = 'genre')   AS genre_hits
FROM tagged
GROUP BY movie_id
ORDER BY score DESC, kw_hits DESC
LIMIT %(limit)s
"""


async def movies_by_genres_and_keywords(
    conn: psycopg.AsyncConnection,
    genre_ids: list[int],
    keyword_ids: list[int],
    limit: int = 50,
) -> list[GraphHit]:
    """Movies tagged with the given genres and/or keywords, ranked by overlap."""
    n_required = len(genre_ids) + len(keyword_ids)
    if n_required == 0:
        return []

    params: dict = {
        "n_required": n_required,
        "limit": limit,
    }
    if genre_ids:
        params["genre_ids"] = genre_ids
    if keyword_ids:
        params["keyword_ids"] = keyword_ids

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_build_tags_sql(genre_ids, keyword_ids), params)
        rows = await cur.fetchall()

    return [
        GraphHit(
            movie_id=r["movie_id"],
            score=float(r["score"]),
            reason=f"{r['kw_hits']} kw + {r['genre_hits']} genre matches",
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# 5. path_between_people — BFS through cast (movie_people, role=actor)
# ---------------------------------------------------------------------------

_SQL_PATH_BETWEEN_PEOPLE = """
WITH RECURSIVE walk AS (
    SELECT
        %(start_id)s AS current_person,
        0 AS depth,
        ARRAY[%(start_id)s] AS person_path,
        ARRAY[]::int[]      AS movie_path
    UNION ALL
    SELECT
        e2.person_id,
        w.depth + 1,
        w.person_path || e2.person_id,
        w.movie_path  || e1.movie_id
    FROM walk w
    JOIN movie_people e1
      ON e1.person_id = w.current_person AND e1.role = 'actor'
    JOIN movie_people e2
      ON e2.movie_id = e1.movie_id
     AND e2.role = 'actor'
     AND e2.person_id <> w.current_person
     AND NOT (e2.person_id = ANY(w.person_path))
    WHERE w.depth < %(max_hops)s
      AND w.current_person <> %(end_id)s
)
SELECT depth, person_path, movie_path
FROM walk
WHERE current_person = %(end_id)s
ORDER BY depth ASC
LIMIT 1
"""


@dataclass
class PersonPath:
    depth: int
    person_path: list[int]
    movie_path: list[int]


async def path_between_people(
    conn: psycopg.AsyncConnection,
    start_id: int,
    end_id: int,
    max_hops: int = 4,
) -> PersonPath | None:
    """Shortest cast-graph path between two people, or None if none within max_hops."""
    if start_id == end_id:
        return PersonPath(depth=0, person_path=[start_id], movie_path=[])

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_SQL_PATH_BETWEEN_PEOPLE, {
            "start_id": start_id,
            "end_id": end_id,
            "max_hops": max_hops,
        })
        row = await cur.fetchone()

    if row is None:
        return None
    return PersonPath(
        depth=row["depth"],
        person_path=list(row["person_path"]),
        movie_path=list(row["movie_path"]),
    )
