from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.movies import router as movies_router
from app.api.query import router as query_router
from app.config import settings
from app.db import close_pool, get_connection, init_pool
from app.limiter import limiter


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_pool()
    yield
    await close_pool()


app = FastAPI(title="Movie RAG", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
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
        "auth_register": "/auth/register",
        "auth_login": "/auth/login",
        "auth_refresh": "/auth/refresh",
        "auth_logout": "/auth/logout",
        "auth_me": "/auth/me",
        "admin": "/admin",
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


app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(query_router, prefix="", tags=["rag"])
app.include_router(movies_router, prefix="", tags=["movies"])
