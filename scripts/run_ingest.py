"""Ingest up to 10_000 movies from TMDB discover into Postgres."""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.ingest.pipeline import MAX_MOVIES, ingest


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest movies from TMDB into Postgres")
    parser.add_argument(
        "--num-movies",
        type=int,
        default=10_000,
        help=f"How many movies to collect from discover (max {MAX_MOVIES})",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="First discover page (use 51 to skip the top 1_000)",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Re-fetch and upsert even if the movie is already in the DB",
    )
    args = parser.parse_args()

    stats = asyncio.run(
        ingest(
            num_movies=args.num_movies,
            skip_existing=not args.no_skip_existing,
            start_page=args.start_page,
        )
    )
    print(f"Summary: {stats}")


if __name__ == "__main__":
    main()
