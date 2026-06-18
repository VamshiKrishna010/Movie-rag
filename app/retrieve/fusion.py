# app/retrieve/fusion.py
"""
Fusion: merge results from multiple retrievers (vector, FTS, graph)
into a single ranked list using Reciprocal Rank Fusion (RRF) with
per-source weights.
"""
from __future__ import annotations

import asyncio
import heapq
from collections import defaultdict
from dataclasses import dataclass, field

from app.db import get_connection
from app.retrieve.graph_retriever import RetrievedChunk


DEFAULT_WEIGHTS: dict[str, float] = {
    "graph":  2.0,
    "vector": 1.0,
    "fts":    0.8,
}

DEFAULT_K_RRF: int = 60


@dataclass
class FusedChunk:
    chunk_id: int
    movie_id: int
    content: str
    score: float
    sources: list[str] = field(default_factory=list)
    per_source_ranks: dict[str, int] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


def reciprocal_rank_fusion(
    result_lists: dict[str, list[RetrievedChunk]],
    *,
    weights: dict[str, float] | None = None,
    k_rrf: int = DEFAULT_K_RRF,
    top_k: int = 10,
) -> list[FusedChunk]:
    weights = weights or DEFAULT_WEIGHTS

    fused_scores: dict[int, float] = defaultdict(float)
    per_source_ranks: dict[int, dict[str, int]] = defaultdict(dict)
    canonical: dict[int, RetrievedChunk] = {}
    sources_seen: dict[int, list[str]] = defaultdict(list)

    for source, results in result_lists.items():
        w = weights.get(source, 1.0)
        for rank, chunk in enumerate(results, start=1):
            cid = chunk.chunk_id
            fused_scores[cid] += w / (k_rrf + rank)
            per_source_ranks[cid][source] = rank
            sources_seen[cid].append(source)
            if cid not in canonical:
                canonical[cid] = chunk

    if not fused_scores:
        return []

    top_ids = heapq.nlargest(
        top_k,
        fused_scores,
        key=fused_scores.__getitem__,
    )

    fused: list[FusedChunk] = []
    for cid in top_ids:
        c = canonical[cid]
        merged_meta = dict(c.metadata)
        merged_meta["fused_sources"] = sources_seen[cid]
        fused.append(FusedChunk(
            chunk_id=cid,
            movie_id=c.movie_id,
            content=c.content,
            score=fused_scores[cid],
            sources=sources_seen[cid],
            per_source_ranks=dict(per_source_ranks[cid]),
            metadata=merged_meta,
        ))

    return fused


async def retrieve_and_fuse(
    conn,
    query: str,
    *,
    k_per_source: int = 20,
    top_k: int = 10,
    weights: dict[str, float] | None = None,
    use_graph: bool = True,
) -> list[FusedChunk]:
    from app.retrieve.hybrid_retriever import retrieve as hybrid_retrieve
    from app.retrieve.graph_retriever import retrieve as graph_retrieve

    if use_graph:
        async with get_connection() as graph_conn:
            hybrid_chunks, graph_chunks = await asyncio.gather(
                hybrid_retrieve(conn, query, k=k_per_source),
                graph_retrieve(graph_conn, query, k=k_per_source),
            )
    else:
        hybrid_chunks = await hybrid_retrieve(conn, query, k=k_per_source)
        graph_chunks = []

    by_source: dict[str, list[RetrievedChunk]] = defaultdict(list)
    for c in hybrid_chunks:
        by_source[c.source].append(c)

    if graph_chunks:
        by_source["graph"] = graph_chunks  # type: ignore[assignment]

    return reciprocal_rank_fusion(
        dict(by_source),
        weights=weights,
        top_k=top_k,
    )
