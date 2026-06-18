"""Hybrid retrieval: dense (pgvector) + sparse (Postgres FTS) fused via RRF."""
from __future__ import annotations

from dataclasses import dataclass

from psycopg.rows import dict_row

from app.db import get_connection
from app.rag.retriever import retrieve_dense
from app.rag.sparse import sparse_retrieve


@dataclass
class FusedChunk:
    chunk_id: int
    movie_id: int
    title: str
    release_year: int | None
    chunk_text: str
    rrf_score: float


def reciprocal_rank_fusion(
    ranked_lists: list[list[int]],
    k: int = 60,
) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


async def hybrid_retrieve(
    query: str,
    k: int = 5,
    k_each: int = 20,
    rrf_k: int = 60,
) -> list[FusedChunk]:
    dense_hits = await retrieve_dense(query, k=k_each)
    dense_ids = [h.chunk_id for h in dense_hits]

    async with get_connection() as conn:
        sparse_hits = await sparse_retrieve(conn, query, k=k_each)
        sparse_ids = [h.chunk_id for h in sparse_hits]

        rrf_scores = reciprocal_rank_fusion([dense_ids, sparse_ids], k=rrf_k)
        if not rrf_scores:
            return []

        top_ids = sorted(rrf_scores, key=rrf_scores.__getitem__, reverse=True)[:k]

        sql = """
            SELECT
                c.id            AS chunk_id,
                c.movie_id      AS movie_id,
                c.content       AS chunk_text,
                m.title         AS title,
                m.release_year  AS release_year
            FROM chunks c
            JOIN movies m ON m.id = c.movie_id
            WHERE c.id = ANY(%(ids)s);
        """
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, {"ids": top_ids})
            rows = await cur.fetchall()

    by_id = {r["chunk_id"]: r for r in rows}
    return [
        FusedChunk(
            chunk_id=cid,
            movie_id=by_id[cid]["movie_id"],
            title=by_id[cid]["title"],
            release_year=by_id[cid]["release_year"],
            chunk_text=by_id[cid]["chunk_text"],
            rrf_score=rrf_scores[cid],
        )
        for cid in top_ids
        if cid in by_id
    ]
