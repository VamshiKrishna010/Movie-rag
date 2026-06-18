import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.rag.retriever import retrieve
from app.rag.generator import generate


async def main():
    question = "What's a good movie about dreams within dreams?"
    chunks = await retrieve(question, k=5)
    print(f"Retrieved {len(chunks)} chunks. Top hit: {chunks[0].title}\n")

    answer = await generate(question, chunks)
    print("Answer:")
    print(answer)


if __name__ == "__main__":
    asyncio.run(main())