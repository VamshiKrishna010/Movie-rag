import asyncio
import sys

import psycopg

from app.config import settings
from app.rag.sparse import sparse_retrieve

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async def main():
    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        hits = await sparse_retrieve(conn, "alien", k=5)
        for h in hits:
            print(f"{h.score:.4f}  movie={h.movie_id}  {h.content[:80]}...")

asyncio.run(main())
