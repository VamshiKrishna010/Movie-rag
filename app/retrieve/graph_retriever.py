# app/retrieve/graph_retriever.py
"""
Graph retriever: wraps the graph router behind the same interface the
hybrid retriever uses, so fusion can treat it as just another source.

Contract (matches your existing retrievers):
    async def retrieve(conn, query, k) -> list[RetrievedChunk]

Internally it does three things:
    1. Ask the router for a GraphPlan (entity extraction + query dispatch).
    2. Convert movie-level GraphHits into chunk-level results by
       fetching chunks for those movies from the DB.
    3. Propagate the graph score onto the chunks so fusion can rank.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.graph.router import GraphPlan, plan_and_execute


@dataclass
class RetrievedChunk:
    """
    The unified shape every retriever in the project returns.
    If your existing hybrid retriever uses a different dataclass,
    swap this import for that one — the fields below are the
    minimum the generator needs.
    """
    chunk_id: int
    movie_id: int
    content: str
    score: float
    source: str          # "vector" | "fts" | "graph" — for fusion + logging
    metadata: dict[str, Any]


# ---------------------------------------------------------------------------
# Chunk fetching
# ---------------------------------------------------------------------------
#
# Graph queries return movie_ids. The generator wants chunks. We bridge
# that with one SQL query: given a list of movie_ids (with scores),
# return the best chunks for each.
#
# "Best" here means: prefer the overview/summary chunk over a long cast
# list dump. If your chunker tags chunk_type, we order by that. If not,
# we just take the first chunk per movie (which in your Day 2 chunker
# tends to be the overview).

_SQL_CHUNKS_FOR_MOVIES = """
SELECT
    c.id           AS chunk_id,
    c.movie_id,
    c.content,
    c.chunk_type,
    m.title
FROM chunks c
JOIN movies m ON m.id = c.movie_id
WHERE c.movie_id = ANY(%(movie_ids)s)
ORDER BY
    c.movie_id,
    -- Prefer overview/summary chunks. Adjust ordering if your
    -- chunk_type values are different.
    CASE c.chunk_type
        WHEN 'overview' THEN 0
        WHEN 'summary'  THEN 0
        WHEN 'cast'     THEN 2
        WHEN 'crew'     THEN 3
        ELSE 1
    END,
    c.id
"""


async def _fetch_chunks_for_movies(
    conn: psycopg.AsyncConnection,
    movie_ids: list[int],
    chunks_per_movie: int = 1,
) -> dict[int, list[dict]]:
    """
    Return {movie_id: [chunk rows]} with at most `chunks_per_movie`
    per movie, preserving the priority ordering from the SQL.
    """
    if not movie_ids:
        return {}
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_SQL_CHUNKS_FOR_MOVIES, {"movie_ids": movie_ids})
        rows = await cur.fetchall()

    grouped: dict[int, list[dict]] = {}
    for r in rows:
        bucket = grouped.setdefault(r["movie_id"], [])
        if len(bucket) < chunks_per_movie:
            bucket.append(r)
    return grouped


# ---------------------------------------------------------------------------
# Public retriever
# ---------------------------------------------------------------------------

async def retrieve(
    conn: psycopg.AsyncConnection,
    query: str,
    k: int = 10,
    *,
    chunks_per_movie: int = 1,
    return_plan: bool = False,
) -> list[RetrievedChunk] | tuple[list[RetrievedChunk], GraphPlan]:
    """
    Graph retrieval entry point.

    Args:
        conn:              Async DB connection.
        query:             Raw user query.
        k:                 Max chunks to return.
        chunks_per_movie:  How many chunks to pull per matched movie.
                           1 keeps the response tight; bump to 2-3 if
                           you want richer context per hit.
        return_plan:       If True, also return the GraphPlan for
                           debugging / observability.

    Returns an empty list when the question isn't graph-shaped, so the
    caller can fall back to hybrid retrieval cleanly.
    """
    plan = await plan_and_execute(conn, query, limit=max(k * 2, 30))

    if plan.intent == "none" or not plan.hits:
        return ([], plan) if return_plan else []

    # Take the top movies by graph score, fetch their chunks.
    top_hits = heapq.nlargest(k, plan.hits, key=lambda h: h.score)
    movie_ids = [h.movie_id for h in top_hits]
    chunks_by_movie = await _fetch_chunks_for_movies(
        conn, movie_ids, chunks_per_movie=chunks_per_movie
    )

    # Build the unified result list, preserving graph score order.
    results: list[RetrievedChunk] = []
    for hit in top_hits:
        for row in chunks_by_movie.get(hit.movie_id, []):
            results.append(RetrievedChunk(
                chunk_id=row["chunk_id"],
                movie_id=row["movie_id"],
                content=row["content"],
                score=hit.score,                    # propagate graph score
                source="graph",
                metadata={
                    "title": row["title"],
                    "chunk_type": row["chunk_type"],
                    "graph_reason": hit.reason,     # why graph picked this
                    "intent": plan.intent,
                },
            ))
            if len(results) >= k:
                break
        if len(results) >= k:
            break

    return (results, plan) if return_plan else results
