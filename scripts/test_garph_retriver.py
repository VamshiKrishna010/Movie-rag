import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import psycopg

from app.config import settings
from app.retrieve.fusion import retrieve_and_fuse
from app.retrieve.graph_retriever import retrieve


def _fmt_entities(plan) -> str:
    return ", ".join(
        f"{e.type}:{e.name}({e.id})" for e in plan.entities
    )


async def main() -> None:
    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        fused = await retrieve_and_fuse(
            conn,
            "What did Nolan direct with Christian Bale?",
            top_k=5,
        )
        print("FUSION:", len(fused), "chunks")
        for r in fused:
            print(f"  {r.metadata.get('title', '?'):30} sources={r.sources}")

        r1, p1 = await retrieve(
            conn,
            "What did Nolan direct with Christian Bale?",
            k=5,
            return_plan=True,
        )
        print("Q1:", p1.intent, "->", len(r1), "chunks")
        print("  entities:", _fmt_entities(p1))
        for note in p1.notes:
            print(f"  note: {note}")
        for r in r1:
            print(
                f"  {r.metadata['title']:30} "
                f"score={r.score:.2f} reason={r.metadata['graph_reason']}"
            )

        # Semantic question — no strong TMDB entity matches.
        r2, p2 = await retrieve(
            conn,
            "what makes a story emotionally compelling for audiences",
            k=5,
            return_plan=True,
        )
        print("Q2:", p2.intent, "->", len(r2), "chunks")
        print("  entities:", _fmt_entities(p2) or "(none)")
        for note in p2.notes:
            print(f"  note: {note}")

        r3, p3 = await retrieve(
            conn,
            "movies similar to Inception",
            k=5,
            return_plan=True,
        )
        print("Q3:", p3.intent, "->", len(r3), "chunks")
        print("  entities:", _fmt_entities(p3))
        for note in p3.notes:
            print(f"  note: {note}")
        for r in r3:
            print(
                f"  {r.metadata['title']:30} "
                f"score={r.score:.2f} reason={r.metadata['graph_reason']}"
            )


asyncio.run(main())
