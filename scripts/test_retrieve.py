import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.rag.retriever import retrieve


async def main():
    results = await retrieve("movies about dreams within dreams", k=5)
    for hit in results:
        print(f"{hit.distance:.4f}  {hit.title} ({hit.release_year})")
        print(f"   {hit.chunk_text[:120]}...")
        print()


asyncio.run(main())