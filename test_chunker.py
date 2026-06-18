import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import psycopg
from app.config import settings
from app.ingest.chunker import build_chunks


async def main():
    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        chunks = await build_chunks(conn)
    print(f"Built {len(chunks)} chunks")
    print()
    print("=== Sample chunk ===")
    print(chunks[0][1])
    print()
    print("=== Another sample ===")
    print(chunks[5][1])


if __name__ == "__main__":
    asyncio.run(main())