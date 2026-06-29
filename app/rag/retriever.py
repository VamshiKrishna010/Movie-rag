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


_CANDIDATE_MULTIPLIER = 4
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
    WITH tsq AS (
      SELECT websearch_to_tsquery('english', %(question)s) AS q
    )
    SELECT
      c.id AS chunk_id,
      ROW_NUMBER() OVER (
        ORDER BY ts_rank(c.search_vector, tsq.q) DESC
      ) AS rank
    FROM chunks c, tsq
    WHERE c.search_vector @@ tsq.q
    ORDER BY ts_rank(c.search_vector, tsq.q) DESC
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
  c.id           AS chunk_id,
  c.movie_id     AS movie_id,
  m.title,
  m.release_year,
  c.content      AS chunk_text,
  fused.rrf_score
FROM fused
JOIN chunks c ON c.id = fused.chunk_id
JOIN movies m ON m.id = c.movie_id
ORDER BY fused.rrf_score DESC
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
    WITH tsq AS (
      SELECT websearch_to_tsquery('english', %(question)s) AS q
    )
    SELECT
      c.id AS chunk_id,
      ROW_NUMBER() OVER (
        ORDER BY ts_rank(c.search_vector, tsq.q) DESC
      ) AS rank
    FROM chunks c, tsq
    WHERE c.search_vector @@ tsq.q
    ORDER BY ts_rank(c.search_vector, tsq.q) DESC
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
SELECT
  c.id           AS chunk_id,
  c.movie_id     AS movie_id,
  m.title,
  m.release_year,
  c.content      AS chunk_text,
  1 - (c.embedding <=> %(vec)s::vector) AS rrf_score
FROM chunks c
JOIN movies m ON m.id = c.movie_id
ORDER BY c.embedding <=> %(vec)s::vector
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
    return {
        "vec": query_vec,
        "question": question,
        "candidate_pool": k * _CANDIDATE_MULTIPLIER,
        "rrf_k": _RRF_K,
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
