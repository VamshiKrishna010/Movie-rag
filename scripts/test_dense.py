# scripts/test_dense.py
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag.retriever import retrieve_dense

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def main():
    hits = await retrieve_dense("movies about loneliness in space", k=5)
    for h in hits:
        print(f"{h.rrf_score:.4f}  {h.title} ({h.release_year})")


asyncio.run(main())
