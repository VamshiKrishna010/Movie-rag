"""Ingest up to 10_000 movies, then chunk + embed any missing."""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Unbuffered progress when stdout is piped to a log file.
sys.stdout.reconfigure(line_buffering=True)

from app.ingest.pipeline import MAX_MOVIES, ingest
from app.ingest.store import embed_and_store


async def run(num_movies: int, start_page: int, skip_existing: bool, full_rebuild: bool) -> None:
    print("=== Step 1/2: TMDB ingest ===")
    stats = await ingest(
        num_movies=num_movies,
        skip_existing=skip_existing,
        start_page=start_page,
    )
    print(f"Ingest summary: {stats}\n")

    print("=== Step 2/2: Chunk + embed ===")
    embedded = await embed_and_store(full_rebuild=full_rebuild)
    print(f"\nAll done. Embedded {embedded} new chunks.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest movies from TMDB, then chunk and embed",
    )
    parser.add_argument("--num-movies", type=int, default=10_000)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--no-skip-existing", action="store_true")
    parser.add_argument(
        "--full-rebuild",
        action="store_true",
        help="Re-embed all movies (not just missing chunks)",
    )
    args = parser.parse_args()

    asyncio.run(
        run(
            num_movies=min(args.num_movies, MAX_MOVIES),
            start_page=args.start_page,
            skip_existing=not args.no_skip_existing,
            full_rebuild=args.full_rebuild,
        )
    )


if __name__ == "__main__":
    main()
