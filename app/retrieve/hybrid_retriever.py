"""Hybrid retriever adapter for multi-source fusion.

Runs vector and FTS searches in parallel on separate pooled connections.
"""
from __future__ import annotations

import asyncio

import psycopg
from psycopg.rows import dict_row

from app.db import get_connection
from app.ingest.embedder import embed_query_async
from app.rag.sparse import sparse_retrieve
from app.retrieve.graph_retriever import RetrievedChunk

_VECTOR_SQL = """
SELECT
    c.id           AS chunk_id,
    c.movie_id     AS movie_id,
    c.content      AS content,
    m.title        AS title,
    m.release_year AS release_year,
    1 - (c.embedding <=> %(vec)s::vector) AS score
FROM chunks c
JOIN movies m ON m.id = c.movie_id
ORDER BY c.embedding <=> %(vec)s::vector
LIMIT %(k)s;
"""


async def _vector_search(query: str, k: int) -> list[dict]:
    query_vec = await embed_query_async(query)
    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_VECTOR_SQL, {"vec": query_vec, "k": k})
            return await cur.fetchall()


async def _fts_search(query: str, k: int) -> list:
    async with get_connection() as conn:
        return await sparse_retrieve(conn, query, k=k)


async def retrieve(
    conn: psycopg.AsyncConnection,
    query: str,
    k: int = 20,
) -> list[RetrievedChunk]:
    # conn kept for API compatibility; vector + FTS run in parallel on pool.
    del conn
    vector_rows, fts_hits = await asyncio.gather(
        _vector_search(query, k),
        _fts_search(query, k),
    )

    results: list[RetrievedChunk] = []
    for row in vector_rows:
        results.append(RetrievedChunk(
            chunk_id=row["chunk_id"],
            movie_id=row["movie_id"],
            content=row["content"],
            score=float(row["score"]),
            source="vector",
            metadata={
                "title": row["title"],
                "release_year": row["release_year"],
            },
        ))
    for hit in fts_hits:
        results.append(RetrievedChunk(
            chunk_id=hit.chunk_id,
            movie_id=hit.movie_id,
            content=hit.content,
            score=hit.score,
            source="fts",
            metadata={},
        ))

    return results
