"""Chunk and embed movies (incremental by default)."""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.ingest.store import embed_and_store


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk and embed movies into pgvector")
    parser.add_argument(
        "--full-rebuild",
        action="store_true",
        help="Delete all chunks and re-embed every movie",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=512,
        help="Movies per embed wave (lower if you run out of RAM)",
    )
    args = parser.parse_args()

    asyncio.run(
        embed_and_store(full_rebuild=args.full_rebuild, embed_batch=args.batch_size)
    )


if __name__ == "__main__":
    main()
