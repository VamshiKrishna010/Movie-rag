import asyncio
from collections import deque
from contextlib import asynccontextmanager

import psycopg
from pgvector.psycopg import register_vector_async

from app.config import settings

_POOL_SIZE = 12
_pool: deque[psycopg.AsyncConnection] | None = None
_pool_lock = asyncio.Lock()


async def _open_connection() -> psycopg.AsyncConnection:
    conn = await psycopg.AsyncConnection.connect(settings.database_url)
    await register_vector_async(conn)
    return conn


async def init_pool() -> None:
    """Warm the connection pool at app startup."""
    global _pool
    _pool = deque()
    for _ in range(_POOL_SIZE):
        _pool.append(await _open_connection())


async def close_pool() -> None:
    """Drain and close all pooled connections at shutdown."""
    global _pool
    if _pool is None:
        return
    while _pool:
        conn = _pool.popleft()
        await conn.close()
    _pool = None


async def _release(conn: psycopg.AsyncConnection) -> None:
    """Reset transaction state and return the connection to the pool.

    A rollback clears any open or aborted transaction so the next caller gets a
    clean connection (psycopg defaults to autocommit=False). If the connection
    is dead, the rollback raises and we close it instead of pooling it.
    """
    try:
        await conn.rollback()
    except Exception:
        await conn.close()
        return
    async with _pool_lock:
        if _pool is not None and len(_pool) < _POOL_SIZE:
            _pool.append(conn)
        else:
            await conn.close()


@asynccontextmanager
async def get_connection():
    """Yield a pooled psycopg connection with pgvector types registered."""
    if _pool is None:
        conn = await _open_connection()
        try:
            yield conn
        finally:
            await conn.close()
        return

    async with _pool_lock:
        conn = _pool.popleft() if _pool else None
    if conn is None:
        conn = await _open_connection()

    try:
        yield conn
    finally:
        await _release(conn)
