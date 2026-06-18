# scripts/test_hybrid.py
import asyncio
import sys

from app.rag.retriever import retrieve

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def main():
    hits = await retrieve("movies directed by Tarantino", k=5)
    for h in hits:
        print(
            f"RRF={h.rrf_score:.4f}  {h.title} ({h.release_year})  "
            f"{h.chunk_text[:70]}..."
        )

asyncio.run(main())
