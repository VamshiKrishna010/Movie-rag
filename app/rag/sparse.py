"""Sparse (lexical) retriever using Postgres full-text search.

Pairs with the dense (pgvector) retriever for hybrid retrieval.
Uses websearch_to_tsquery for forgiving query parsing and ts_rank_cd
(cover density) for ranking.
"""
from __future__ import annotations

from dataclasses import dataclass

from psycopg import AsyncConnection
from psycopg.rows import dict_row


@dataclass
class SparseHit:
    chunk_id: int
    movie_id: int
    content: str
    score: float  # ts_rank_cd score; higher is better


async def sparse_retrieve(
    conn: AsyncConnection,
    query: str,
    k: int = 20,
) -> list[SparseHit]:
    """Return top-k chunks by lexical match against the query.

    Uses websearch_to_tsquery so user input like 'sci-fi "space opera" -horror'
    parses sensibly without raising. Returns [] if the query has no
    indexable terms (e.g. all stopwords).
    """
    sql = """
        SELECT
            c.id          AS chunk_id,
            c.movie_id    AS movie_id,
            c.content     AS content,
            ts_rank_cd(c.search_vector, q) AS score
        FROM chunks c,
             websearch_to_tsquery('english', %s) AS q
        WHERE c.search_vector @@ q
        ORDER BY score DESC
        LIMIT %s;
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (query, k))
        rows = await cur.fetchall()

    return [
        SparseHit(
            chunk_id=r["chunk_id"],
            movie_id=r["movie_id"],
            content=r["content"],
            score=float(r["score"]),
        )
        for r in rows
    ]
