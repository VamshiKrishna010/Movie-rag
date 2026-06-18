from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.deps import get_current_user
from app.db import get_connection
from app.rag.generator import generate
from app.rag.retriever import RetrievedChunk, retrieve
from app.retrieve.fusion import retrieve_and_fuse


router = APIRouter()


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=250)
    k: int = Field(default=5, ge=1, le=20)
    include_chunks: bool = False


class RetrievedChunkOut(BaseModel):
    movie_id: int
    title: str
    release_year: int | None
    rrf_score: float
    chunk_preview: str
    chunk_text: str | None = None


class QueryResponse(BaseModel):
    question: str
    answer: str
    retrieved: List[RetrievedChunkOut]


def _fused_to_chunks(fused) -> List[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id=f.chunk_id,
            movie_id=f.movie_id,
            title=f.metadata.get("title") or "",
            release_year=f.metadata.get("release_year"),
            chunk_text=f.content,
            rrf_score=f.score,
        )
        for f in fused
    ]


async def _enrich_titles(chunks: List[RetrievedChunk]) -> List[RetrievedChunk]:
    missing = [c.chunk_id for c in chunks if not c.title]
    if not missing:
        return chunks
    from psycopg.rows import dict_row

    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT c.id AS chunk_id, m.title, m.release_year
                FROM chunks c
                JOIN movies m ON m.id = c.movie_id
                WHERE c.id = ANY(%(ids)s)
                """,
                {"ids": missing},
            )
            meta = {r["chunk_id"]: r for r in await cur.fetchall()}

    enriched: List[RetrievedChunk] = []
    for c in chunks:
        m = meta.get(c.chunk_id)
        enriched.append(
            RetrievedChunk(
                chunk_id=c.chunk_id,
                movie_id=c.movie_id,
                title=c.title or (m["title"] if m else ""),
                release_year=c.release_year if c.release_year is not None else (m["release_year"] if m else None),
                chunk_text=c.chunk_text,
                rrf_score=c.rrf_score,
            )
        )
    return enriched


async def _retrieve(question: str, k: int) -> List[RetrievedChunk]:
    async with get_connection() as conn:
        fused = await retrieve_and_fuse(
            conn,
            question,
            k_per_source=max(k * 4, 20),
            top_k=k,
            use_graph=True,
        )
    if fused:
        return await _enrich_titles(_fused_to_chunks(fused))
    return await retrieve(question, k=k)


@router.post("/query", response_model=QueryResponse)
async def query(
    req: QueryRequest,
    _current_user: Annotated[dict, Depends(get_current_user)],
) -> QueryResponse:
    try:
        chunks = await _retrieve(req.question, k=req.k)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {e}")

    if not chunks:
        raise HTTPException(status_code=404, detail="No relevant movies found.")

    try:
        answer = await generate(req.question, chunks)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

    return QueryResponse(
        question=req.question,
        answer=answer,
        retrieved=[
            RetrievedChunkOut(
                movie_id=c.movie_id,
                title=c.title,
                release_year=c.release_year,
                rrf_score=c.rrf_score,
                chunk_preview=c.chunk_text[:200],
                chunk_text=c.chunk_text if req.include_chunks else None,
            )
            for c in chunks
        ],
    )
