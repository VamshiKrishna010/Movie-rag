from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.deps import require_scopes
from app.auth.scopes import CHAT_USE
from app.rag.generator import generate
from app.rag.retriever import RetrievedChunk, retrieve_routed
from app.rag.routing import QueryRoute


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
    retrieval_category: str
    retrieval_strategy: str
    answer: str
    retrieved: List[RetrievedChunkOut]


async def _retrieve(question: str, k: int) -> tuple[List[RetrievedChunk], QueryRoute]:
    return await retrieve_routed(question, k=k)


@router.post("/query", response_model=QueryResponse)
async def query(
    req: QueryRequest,
    _current_user: Annotated[dict, Depends(require_scopes(CHAT_USE))],
) -> QueryResponse:
    try:
        chunks, route = await _retrieve(req.question, k=req.k)
    except Exception:
        raise HTTPException(status_code=500, detail="Retrieval failed")

    if not chunks:
        raise HTTPException(status_code=404, detail="No relevant movies found.")

    try:
        answer = await generate(req.question, chunks)
    except Exception:
        raise HTTPException(status_code=500, detail="Generation failed")

    return QueryResponse(
        question=req.question,
        retrieval_category=route.category,
        retrieval_strategy=route.strategy,
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
