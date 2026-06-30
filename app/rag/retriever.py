"""
Hybrid retriever: vector search + Postgres full-text search, fused via RRF.

The query runs two searches in parallel inside one SQL statement:

  1. Vector search   — semantic similarity (pgvector cosine distance)
  2. FTS search      — keyword match (Postgres tsvector / tsquery)

Each side ranks its own top candidates. We then fuse the two ranked lists
with Reciprocal Rank Fusion:

        rrf_score(chunk) = 1/(60 + rank_vector) + 1/(60 + rank_fts)

A chunk that ranks well on *either* side gets some score; a chunk that ranks
well on *both* sides gets a lot. The constant 60 is the standard RRF value
(Cormack et al., 2009) — there's nothing to tune.
"""
from dataclasses import dataclass
from typing import List

import psycopg
from pgvector.psycopg import register_vector_async
from psycopg.rows import dict_row

from app.db import get_connection
from app.ingest.embedder import embed_query_async
from app.rag.routing import QueryRoute, RetrievalStrategy, route_query
from app.rag.sparse import build_loose_tsquery


@dataclass
class RetrievedChunk:
    chunk_id: int
    movie_id: int
    title: str
    release_year: int | None
    chunk_text: str
    rrf_score: float


@dataclass
class MovieRanking:
    movie_id: int
    rrf_score: float


_CANDIDATE_MULTIPLIER = 12
_RRF_K = 60


_HYBRID_SQL = """
WITH
  vector_search AS (
    SELECT
      c.id AS chunk_id,
      ROW_NUMBER() OVER (ORDER BY c.embedding <=> %(vec)s::vector) AS rank
    FROM chunks c
    ORDER BY c.embedding <=> %(vec)s::vector
    LIMIT %(candidate_pool)s
  ),
  fts_search AS (
    WITH query_terms AS (
      SELECT
        websearch_to_tsquery('english', %(question)s) AS strict_q,
        CASE
          WHEN %(loose_tsquery)s = '' THEN NULL
          ELSE to_tsquery('english', %(loose_tsquery)s)
        END AS loose_q,
        ' ' || trim(
          regexp_replace(lower(%(question)s), '[^[:alnum:]]+', ' ', 'g')
        ) || ' ' AS query_norm
    ),
    mentioned_titles AS (
      SELECT m.id
      FROM movies m, query_terms qt
      CROSS JOIN LATERAL (
        SELECT trim(
          regexp_replace(lower(m.title), '[^[:alnum:]]+', ' ', 'g')
        ) AS title_norm
      ) n
      WHERE length(n.title_norm) >= 3
        AND qt.query_norm LIKE '%% ' || n.title_norm || ' %%'
    ),
    mentioned_people AS (
      SELECT p.id
      FROM people p, query_terms qt
      CROSS JOIN LATERAL (
        SELECT trim(
          regexp_replace(lower(p.name), '[^[:alnum:]]+', ' ', 'g')
        ) AS person_norm
      ) n
      WHERE length(n.person_norm) >= 5
        AND qt.query_norm LIKE '%% ' || n.person_norm || ' %%'
    ),
    mentioned_title_directors AS (
      SELECT DISTINCT mp.person_id
      FROM mentioned_titles mt
      JOIN movie_people mp
        ON mp.movie_id = mt.id
       AND mp.role = 'director'
    ),
    metadata_movies AS (
      SELECT
        movie_id,
        max(title_match) AS title_match,
        sum(person_matches) AS person_matches,
        sum(director_matches) AS director_matches
      FROM (
        SELECT
          id AS movie_id,
          1 AS title_match,
          0 AS person_matches,
          0 AS director_matches
        FROM mentioned_titles
        UNION ALL
        SELECT
          mp.movie_id,
          0 AS title_match,
          count(DISTINCT mp.person_id) AS person_matches,
          0 AS director_matches
        FROM movie_people mp
        WHERE mp.person_id IN (SELECT id FROM mentioned_people)
        GROUP BY mp.movie_id
        UNION ALL
        SELECT
          mp.movie_id,
          0 AS title_match,
          0 AS person_matches,
          count(DISTINCT mp.person_id) AS director_matches
        FROM movie_people mp
        WHERE mp.role = 'director'
          AND mp.person_id IN (SELECT person_id FROM mentioned_title_directors)
        GROUP BY mp.movie_id
      ) matches
      GROUP BY movie_id
    ),
    fts_chunks AS (
      SELECT
        c.id AS chunk_id,
        (
          4.0 * ts_rank_cd(c.search_vector, qt.strict_q)
          + COALESCE(ts_rank_cd(c.search_vector, qt.loose_q), 0)
        ) AS fts_score
      FROM chunks c
      CROSS JOIN query_terms qt
      WHERE c.search_vector @@ qt.strict_q
         OR (qt.loose_q IS NOT NULL AND c.search_vector @@ qt.loose_q)
      ORDER BY fts_score DESC, c.id
      LIMIT %(fts_pool)s
    ),
    candidate_chunks AS (
      SELECT chunk_id FROM fts_chunks
      UNION
      SELECT c.id AS chunk_id
      FROM chunks c
      JOIN metadata_movies mm ON mm.movie_id = c.movie_id
    ),
    scored AS (
      SELECT
        c.id AS chunk_id,
        ts_rank_cd(c.search_vector, qt.strict_q) AS strict_score,
        COALESCE(ts_rank_cd(c.search_vector, qt.loose_q), 0) AS loose_score,
        COALESCE(mm.title_match, 0) AS title_match,
        COALESCE(mm.person_matches, 0) AS person_matches,
        COALESCE(mm.director_matches, 0) AS director_matches,
        (
          4.0 * ts_rank_cd(c.search_vector, qt.strict_q)
          + COALESCE(ts_rank_cd(c.search_vector, qt.loose_q), 0)
          + 3.0 * COALESCE(mm.title_match, 0)
          + 1.8 * COALESCE(mm.person_matches, 0)
          + 1.2 * COALESCE(mm.director_matches, 0)
          + CASE c.chunk_type
              WHEN 'themes' THEN 0.05
              WHEN 'plot' THEN 0.03
              ELSE 0.01
            END
        ) AS score
      FROM candidate_chunks cc
      JOIN chunks c ON c.id = cc.chunk_id
      CROSS JOIN query_terms qt
      LEFT JOIN metadata_movies mm ON mm.movie_id = c.movie_id
    )
    SELECT
      chunk_id,
      ROW_NUMBER() OVER (
        ORDER BY
          score DESC,
          title_match DESC,
          person_matches DESC,
          director_matches DESC,
          strict_score DESC,
          loose_score DESC,
          chunk_id
      ) AS rank
    FROM scored
    ORDER BY
      score DESC,
      title_match DESC,
      person_matches DESC,
      director_matches DESC,
      strict_score DESC,
      loose_score DESC,
      chunk_id
    LIMIT %(candidate_pool)s
  ),
  fused AS (
    SELECT
      COALESCE(v.chunk_id, f.chunk_id) AS chunk_id,
      COALESCE(1.0 / (%(rrf_k)s + v.rank), 0) +
      COALESCE(1.0 / (%(rrf_k)s + f.rank), 0) AS rrf_score
    FROM vector_search v
    FULL OUTER JOIN fts_search f USING (chunk_id)
  ),
  best_movie_chunks AS (
    SELECT chunk_id, rrf_score
    FROM (
      SELECT
        c.id AS chunk_id,
        c.movie_id,
        fused.rrf_score,
        ROW_NUMBER() OVER (
          PARTITION BY c.movie_id
          ORDER BY
            fused.rrf_score DESC,
            CASE c.chunk_type
              WHEN 'themes' THEN 0
              WHEN 'plot' THEN 1
              ELSE 2
            END,
            c.id
        ) AS movie_rank
      FROM fused
      JOIN chunks c ON c.id = fused.chunk_id
    ) ranked
    WHERE movie_rank = 1
  )
SELECT
  c.id           AS chunk_id,
  c.movie_id     AS movie_id,
  m.title,
  m.release_year,
  c.content      AS chunk_text,
  best_movie_chunks.rrf_score
FROM best_movie_chunks
JOIN chunks c ON c.id = best_movie_chunks.chunk_id
JOIN movies m ON m.id = c.movie_id
ORDER BY best_movie_chunks.rrf_score DESC
LIMIT %(k)s;
"""


_MOVIE_RANK_SQL = """
WITH
  vector_search AS (
    SELECT
      c.id AS chunk_id,
      ROW_NUMBER() OVER (ORDER BY c.embedding <=> %(vec)s::vector) AS rank
    FROM chunks c
    ORDER BY c.embedding <=> %(vec)s::vector
    LIMIT %(candidate_pool)s
  ),
  fts_search AS (
    WITH query_terms AS (
      SELECT
        websearch_to_tsquery('english', %(question)s) AS strict_q,
        CASE
          WHEN %(loose_tsquery)s = '' THEN NULL
          ELSE to_tsquery('english', %(loose_tsquery)s)
        END AS loose_q,
        ' ' || trim(
          regexp_replace(lower(%(question)s), '[^[:alnum:]]+', ' ', 'g')
        ) || ' ' AS query_norm
    ),
    mentioned_titles AS (
      SELECT m.id
      FROM movies m, query_terms qt
      CROSS JOIN LATERAL (
        SELECT trim(
          regexp_replace(lower(m.title), '[^[:alnum:]]+', ' ', 'g')
        ) AS title_norm
      ) n
      WHERE length(n.title_norm) >= 3
        AND qt.query_norm LIKE '%% ' || n.title_norm || ' %%'
    ),
    mentioned_people AS (
      SELECT p.id
      FROM people p, query_terms qt
      CROSS JOIN LATERAL (
        SELECT trim(
          regexp_replace(lower(p.name), '[^[:alnum:]]+', ' ', 'g')
        ) AS person_norm
      ) n
      WHERE length(n.person_norm) >= 5
        AND qt.query_norm LIKE '%% ' || n.person_norm || ' %%'
    ),
    mentioned_title_directors AS (
      SELECT DISTINCT mp.person_id
      FROM mentioned_titles mt
      JOIN movie_people mp
        ON mp.movie_id = mt.id
       AND mp.role = 'director'
    ),
    metadata_movies AS (
      SELECT
        movie_id,
        max(title_match) AS title_match,
        sum(person_matches) AS person_matches,
        sum(director_matches) AS director_matches
      FROM (
        SELECT
          id AS movie_id,
          1 AS title_match,
          0 AS person_matches,
          0 AS director_matches
        FROM mentioned_titles
        UNION ALL
        SELECT
          mp.movie_id,
          0 AS title_match,
          count(DISTINCT mp.person_id) AS person_matches,
          0 AS director_matches
        FROM movie_people mp
        WHERE mp.person_id IN (SELECT id FROM mentioned_people)
        GROUP BY mp.movie_id
        UNION ALL
        SELECT
          mp.movie_id,
          0 AS title_match,
          0 AS person_matches,
          count(DISTINCT mp.person_id) AS director_matches
        FROM movie_people mp
        WHERE mp.role = 'director'
          AND mp.person_id IN (SELECT person_id FROM mentioned_title_directors)
        GROUP BY mp.movie_id
      ) matches
      GROUP BY movie_id
    ),
    fts_chunks AS (
      SELECT
        c.id AS chunk_id,
        (
          4.0 * ts_rank_cd(c.search_vector, qt.strict_q)
          + COALESCE(ts_rank_cd(c.search_vector, qt.loose_q), 0)
        ) AS fts_score
      FROM chunks c
      CROSS JOIN query_terms qt
      WHERE c.search_vector @@ qt.strict_q
         OR (qt.loose_q IS NOT NULL AND c.search_vector @@ qt.loose_q)
      ORDER BY fts_score DESC, c.id
      LIMIT %(fts_pool)s
    ),
    candidate_chunks AS (
      SELECT chunk_id FROM fts_chunks
      UNION
      SELECT c.id AS chunk_id
      FROM chunks c
      JOIN metadata_movies mm ON mm.movie_id = c.movie_id
    ),
    scored AS (
      SELECT
        c.id AS chunk_id,
        ts_rank_cd(c.search_vector, qt.strict_q) AS strict_score,
        COALESCE(ts_rank_cd(c.search_vector, qt.loose_q), 0) AS loose_score,
        COALESCE(mm.title_match, 0) AS title_match,
        COALESCE(mm.person_matches, 0) AS person_matches,
        COALESCE(mm.director_matches, 0) AS director_matches,
        (
          4.0 * ts_rank_cd(c.search_vector, qt.strict_q)
          + COALESCE(ts_rank_cd(c.search_vector, qt.loose_q), 0)
          + 3.0 * COALESCE(mm.title_match, 0)
          + 1.8 * COALESCE(mm.person_matches, 0)
          + 1.2 * COALESCE(mm.director_matches, 0)
          + CASE c.chunk_type
              WHEN 'themes' THEN 0.05
              WHEN 'plot' THEN 0.03
              ELSE 0.01
            END
        ) AS score
      FROM candidate_chunks cc
      JOIN chunks c ON c.id = cc.chunk_id
      CROSS JOIN query_terms qt
      LEFT JOIN metadata_movies mm ON mm.movie_id = c.movie_id
    )
    SELECT
      chunk_id,
      ROW_NUMBER() OVER (
        ORDER BY
          score DESC,
          title_match DESC,
          person_matches DESC,
          director_matches DESC,
          strict_score DESC,
          loose_score DESC,
          chunk_id
      ) AS rank
    FROM scored
    ORDER BY
      score DESC,
      title_match DESC,
      person_matches DESC,
      director_matches DESC,
      strict_score DESC,
      loose_score DESC,
      chunk_id
    LIMIT %(candidate_pool)s
  ),
  fused AS (
    SELECT
      COALESCE(v.chunk_id, f.chunk_id) AS chunk_id,
      COALESCE(1.0 / (%(rrf_k)s + v.rank), 0) +
      COALESCE(1.0 / (%(rrf_k)s + f.rank), 0) AS rrf_score
    FROM vector_search v
    FULL OUTER JOIN fts_search f USING (chunk_id)
  )
SELECT
  c.movie_id,
  MAX(fused.rrf_score) AS rrf_score
FROM fused
JOIN chunks c ON c.id = fused.chunk_id
GROUP BY c.movie_id
ORDER BY rrf_score DESC
LIMIT %(k)s;
"""


_DENSE_SQL = """
WITH ranked AS (
  SELECT
    c.id           AS chunk_id,
    c.movie_id     AS movie_id,
    m.title,
    m.release_year,
    c.content      AS chunk_text,
    c.embedding <=> %(vec)s::vector AS distance,
    ROW_NUMBER() OVER (
      PARTITION BY c.movie_id
      ORDER BY
        c.embedding <=> %(vec)s::vector,
        CASE c.chunk_type
          WHEN 'themes' THEN 0
          WHEN 'plot' THEN 1
          ELSE 2
        END
    ) AS movie_rank
  FROM chunks c
  JOIN movies m ON m.id = c.movie_id
)
SELECT
  chunk_id,
  movie_id,
  title,
  release_year,
  chunk_text,
  1 - distance AS rrf_score
FROM ranked
WHERE movie_rank = 1
ORDER BY distance
LIMIT %(k)s;
"""

_SPARSE_SQL = """
WITH query_terms AS (
  SELECT
    websearch_to_tsquery('english', %(question)s) AS strict_q,
    CASE
      WHEN %(loose_tsquery)s = '' THEN NULL
      ELSE to_tsquery('english', %(loose_tsquery)s)
    END AS loose_q,
    ' ' || trim(
      regexp_replace(lower(%(question)s), '[^[:alnum:]]+', ' ', 'g')
    ) || ' ' AS query_norm
),
mentioned_titles AS (
  SELECT m.id
  FROM movies m, query_terms qt
  CROSS JOIN LATERAL (
    SELECT trim(
      regexp_replace(lower(m.title), '[^[:alnum:]]+', ' ', 'g')
    ) AS title_norm
  ) n
  WHERE length(n.title_norm) >= 3
    AND qt.query_norm LIKE '%% ' || n.title_norm || ' %%'
),
mentioned_people AS (
  SELECT p.id
  FROM people p, query_terms qt
  CROSS JOIN LATERAL (
    SELECT trim(
      regexp_replace(lower(p.name), '[^[:alnum:]]+', ' ', 'g')
    ) AS person_norm
  ) n
  WHERE length(n.person_norm) >= 5
    AND qt.query_norm LIKE '%% ' || n.person_norm || ' %%'
),
mentioned_title_directors AS (
  SELECT DISTINCT mp.person_id
  FROM mentioned_titles mt
  JOIN movie_people mp
    ON mp.movie_id = mt.id
   AND mp.role = 'director'
),
metadata_movies AS (
  SELECT
    movie_id,
    max(title_match) AS title_match,
    sum(person_matches) AS person_matches,
    sum(director_matches) AS director_matches
  FROM (
    SELECT
      id AS movie_id,
      1 AS title_match,
      0 AS person_matches,
      0 AS director_matches
    FROM mentioned_titles
    UNION ALL
    SELECT
      mp.movie_id,
      0 AS title_match,
      count(DISTINCT mp.person_id) AS person_matches,
      0 AS director_matches
    FROM movie_people mp
    WHERE mp.person_id IN (SELECT id FROM mentioned_people)
    GROUP BY mp.movie_id
    UNION ALL
    SELECT
      mp.movie_id,
      0 AS title_match,
      0 AS person_matches,
      count(DISTINCT mp.person_id) AS director_matches
    FROM movie_people mp
    WHERE mp.role = 'director'
      AND mp.person_id IN (SELECT person_id FROM mentioned_title_directors)
    GROUP BY mp.movie_id
  ) matches
  GROUP BY movie_id
),
fts_chunks AS (
  SELECT
    c.id AS chunk_id,
    (
      4.0 * ts_rank_cd(c.search_vector, qt.strict_q)
      + COALESCE(ts_rank_cd(c.search_vector, qt.loose_q), 0)
    ) AS fts_score
  FROM chunks c
  CROSS JOIN query_terms qt
  WHERE c.search_vector @@ qt.strict_q
     OR (qt.loose_q IS NOT NULL AND c.search_vector @@ qt.loose_q)
  ORDER BY fts_score DESC, c.id
  LIMIT %(fts_pool)s
),
candidate_chunks AS (
  SELECT chunk_id FROM fts_chunks
  UNION
  SELECT c.id AS chunk_id
  FROM chunks c
  JOIN metadata_movies mm ON mm.movie_id = c.movie_id
),
ranked AS (
  SELECT
    c.id AS chunk_id,
    c.movie_id,
    m.title,
    m.release_year,
    c.content AS chunk_text,
    ts_rank_cd(c.search_vector, qt.strict_q) AS strict_score,
    COALESCE(ts_rank_cd(c.search_vector, qt.loose_q), 0) AS loose_score,
    COALESCE(mm.title_match, 0) AS title_match,
    COALESCE(mm.person_matches, 0) AS person_matches,
    COALESCE(mm.director_matches, 0) AS director_matches,
    (
      4.0 * ts_rank_cd(c.search_vector, qt.strict_q)
      + COALESCE(ts_rank_cd(c.search_vector, qt.loose_q), 0)
      + 3.0 * COALESCE(mm.title_match, 0)
      + 1.8 * COALESCE(mm.person_matches, 0)
      + 1.2 * COALESCE(mm.director_matches, 0)
      + CASE c.chunk_type
          WHEN 'themes' THEN 0.05
          WHEN 'plot' THEN 0.03
          ELSE 0.01
        END
    ) AS score,
    ROW_NUMBER() OVER (
      PARTITION BY c.movie_id
      ORDER BY
        (
          4.0 * ts_rank_cd(c.search_vector, qt.strict_q)
          + COALESCE(ts_rank_cd(c.search_vector, qt.loose_q), 0)
          + 3.0 * COALESCE(mm.title_match, 0)
          + 1.8 * COALESCE(mm.person_matches, 0)
          + 1.2 * COALESCE(mm.director_matches, 0)
          + CASE c.chunk_type
              WHEN 'themes' THEN 0.05
              WHEN 'plot' THEN 0.03
              ELSE 0.01
            END
        ) DESC,
        COALESCE(mm.title_match, 0) DESC,
        COALESCE(mm.person_matches, 0) DESC,
        COALESCE(mm.director_matches, 0) DESC,
        ts_rank_cd(c.search_vector, qt.strict_q) DESC,
        COALESCE(ts_rank_cd(c.search_vector, qt.loose_q), 0) DESC,
        CASE c.chunk_type
          WHEN 'themes' THEN 0
          WHEN 'plot' THEN 1
          ELSE 2
        END,
        c.id
    ) AS movie_rank
  FROM candidate_chunks cc
  JOIN chunks c ON c.id = cc.chunk_id
  JOIN movies m ON m.id = c.movie_id
  CROSS JOIN query_terms qt
  LEFT JOIN metadata_movies mm ON mm.movie_id = c.movie_id
)
SELECT
  chunk_id,
  movie_id,
  title,
  release_year,
  chunk_text,
  score AS rrf_score
FROM ranked
WHERE movie_rank = 1
ORDER BY
  score DESC,
  title_match DESC,
  person_matches DESC,
  director_matches DESC,
  strict_score DESC,
  loose_score DESC,
  chunk_id
LIMIT %(k)s;
"""


def _rows_to_chunks(rows: list[dict]) -> List[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id=r["chunk_id"],
            movie_id=r["movie_id"],
            title=r["title"],
            release_year=r["release_year"],
            chunk_text=r["chunk_text"],
            rrf_score=float(r["rrf_score"]),
        )
        for r in rows
    ]


async def _run_query(
    sql: str,
    params: dict,
    conn_str: str | None = None,
) -> list[dict]:
    if conn_str:
        async with await psycopg.AsyncConnection.connect(conn_str) as aconn:
            await register_vector_async(aconn)
            async with aconn.cursor(row_factory=dict_row) as cur:
                await cur.execute(sql, params)
                return await cur.fetchall()
    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()


def _hybrid_params(question: str, query_vec: list[float], k: int) -> dict:
    candidate_pool = max(k * _CANDIDATE_MULTIPLIER, k)
    return {
        "vec": query_vec,
        "question": question,
        "loose_tsquery": build_loose_tsquery(question),
        "fts_pool": max(candidate_pool * 8, 200),
        "candidate_pool": candidate_pool,
        "rrf_k": _RRF_K,
        "k": k,
    }


def _sparse_params(question: str, k: int) -> dict:
    return {
        "question": question,
        "loose_tsquery": build_loose_tsquery(question),
        "fts_pool": max(k * 80, 200),
        "k": k,
    }


async def retrieve_dense(
    question: str,
    k: int = 10,
    conn_str: str | None = None,
) -> List[RetrievedChunk]:
    """Dense-only baseline: nearest neighbors by cosine distance."""
    query_vec = await embed_query_async(question)
    rows = await _run_query(_DENSE_SQL, {"vec": query_vec, "k": k}, conn_str)
    return _rows_to_chunks(rows)


async def retrieve_sparse(
    question: str,
    k: int = 10,
    conn_str: str | None = None,
) -> List[RetrievedChunk]:
    """Sparse-only retrieval using lexical and catalog metadata signals."""
    rows = await _run_query(_SPARSE_SQL, _sparse_params(question, k), conn_str)
    return _rows_to_chunks(rows)


async def retrieve(
    question: str,
    k: int = 5,
    conn_str: str | None = None,
) -> List[RetrievedChunk]:
    query_vec = await embed_query_async(question)
    rows = await _run_query(
        _HYBRID_SQL,
        _hybrid_params(question, query_vec, k),
        conn_str,
    )
    return _rows_to_chunks(rows)


async def retrieve_by_strategy(
    question: str,
    *,
    strategy: RetrievalStrategy,
    k: int = 5,
    conn_str: str | None = None,
) -> List[RetrievedChunk]:
    if strategy == "dense":
        return await retrieve_dense(question, k=k, conn_str=conn_str)
    if strategy == "sparse":
        return await retrieve_sparse(question, k=k, conn_str=conn_str)
    return await retrieve(question, k=k, conn_str=conn_str)


async def retrieve_routed(
    question: str,
    k: int = 5,
    conn_str: str | None = None,
) -> tuple[List[RetrievedChunk], QueryRoute]:
    route = route_query(question)
    chunks = await retrieve_by_strategy(
        question,
        strategy=route.strategy,
        k=k,
        conn_str=conn_str,
    )
    return chunks, route


async def retrieve_movie_rankings(
    question: str,
    k: int = 100,
    conn_str: str | None = None,
) -> list[MovieRanking]:
    """Lightweight hybrid search — movie IDs + scores only (no chunk text)."""
    query_vec = await embed_query_async(question)
    rows = await _run_query(
        _MOVIE_RANK_SQL,
        _hybrid_params(question, query_vec, k),
        conn_str,
    )
    return [
        MovieRanking(movie_id=r["movie_id"], rrf_score=float(r["rrf_score"]))
        for r in rows
    ]
