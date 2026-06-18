from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.movies import router as movies_router
from app.api.query import router as query_router
from app.db import close_pool, get_connection, init_pool


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_pool()
    yield
    await close_pool()


app = FastAPI(title="Movie RAG", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "message": "Movie RAG API is running",
        "docs": "/docs",
        "health": "/health",
        "query": "/query",
        "movies_browse": "/movies/browse",
        "movies_search": "/movies/search",
        "movies_detail": "/movies/{id}",
        "genres": "/genres",
    }


@app.get("/health")
async def health():
    """Confirms the app is up AND can talk to Postgres."""
    async with get_connection() as conn:
        result = await conn.execute("SELECT version()")
        row = await result.fetchone()
        pg_version = row[0] if row else "unknown"

    return {
        "status": "ok",
        "postgres": pg_version,
    }


app.include_router(query_router, prefix="", tags=["rag"])
app.include_router(movies_router, prefix="", tags=["movies"])
