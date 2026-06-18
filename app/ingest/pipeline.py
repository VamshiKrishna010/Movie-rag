import asyncio
import json
from pathlib import Path

import httpx
import psycopg

from app.config import settings
from app.ingest.tmdb_client import discover_movies, get_movie_details

RAW_DIR = Path("data/raw")

DISCOVER_PAGE_SIZE = 20
MAX_DISCOVER_PAGE = 500          # TMDB hard cap for /discover/movie
MAX_MOVIES = MAX_DISCOVER_PAGE * DISCOVER_PAGE_SIZE  # 10_000
DISCOVER_BATCH = 25              # concurrent discover page requests
DETAIL_BATCH = 50                # concurrent detail fetches per wave
DB_COMMIT_BATCH = 50


async def ingest(
    num_movies: int = 10_000,
    *,
    skip_existing: bool = True,
    start_page: int = 1,
) -> dict[str, int]:
    """Pull movies from TMDB discover, cache raw JSON, load into Postgres.

    Args:
        num_movies: Target total from discover (capped at 10_000).
        skip_existing: Skip IDs already in ``movies`` (fast incremental ingest).
        start_page: First discover page (1-based). Use 51 to skip the top 1_000.
    """
    num_movies = min(num_movies, MAX_MOVIES)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    pages_needed = (num_movies + DISCOVER_PAGE_SIZE - 1) // DISCOVER_PAGE_SIZE
    last_page = min(start_page + pages_needed - 1, MAX_DISCOVER_PAGE)
    print(f"Ingest target: {num_movies} movies (discover pages {start_page}–{last_page})")

    movie_ids = await _collect_movie_ids(num_movies, start_page=start_page)
    print(f"Collected {len(movie_ids)} movie IDs")

    if skip_existing:
        existing = await _load_existing_ids()
        to_fetch = [mid for mid in movie_ids if mid not in existing]
        skipped = len(movie_ids) - len(to_fetch)
        print(f"Skipping {skipped} already in DB; fetching {len(to_fetch)} new")
    else:
        to_fetch = movie_ids
        skipped = 0

    if not to_fetch:
        print("Nothing new to ingest.")
        return {"collected": len(movie_ids), "skipped": skipped, "loaded": 0}

    details_list = await _fetch_all_details(to_fetch)
    print(f"Fetched details for {len(details_list)} movies")

    loaded = await _load_into_db(details_list)
    print(f"Loaded {loaded} movies into Postgres")
    return {"collected": len(movie_ids), "skipped": skipped, "loaded": loaded}


async def _load_existing_ids() -> set[int]:
    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM movies")
            rows = await cur.fetchall()
    return {r[0] for r in rows}


async def _collect_movie_ids(cap: int, *, start_page: int = 1) -> list[int]:
    """Fetch discover pages in batches (TMDB returns 20 IDs per page)."""
    pages_needed = (cap + DISCOVER_PAGE_SIZE - 1) // DISCOVER_PAGE_SIZE
    last_page = min(start_page + pages_needed - 1, MAX_DISCOVER_PAGE)

    ids: list[int] = []
    async with httpx.AsyncClient() as client:
        for batch_start in range(start_page, last_page + 1, DISCOVER_BATCH):
            batch_end = min(batch_start + DISCOVER_BATCH, last_page + 1)
            tasks = [discover_movies(client, page=p) for p in range(batch_start, batch_end)]
            results = await asyncio.gather(*tasks)
            for page_data in results:
                for movie in page_data["results"]:
                    ids.append(movie["id"])
                    if len(ids) >= cap:
                        return ids
            print(f"  discover pages {batch_start}–{batch_end - 1}: {len(ids)} IDs so far")
    return ids


async def _fetch_all_details(movie_ids: list[int]) -> list[dict]:
    """Fetch full details in waves to avoid thousands of simultaneous tasks."""
    results: list[dict] = []
    async with httpx.AsyncClient() as client:
        for i in range(0, len(movie_ids), DETAIL_BATCH):
            batch = movie_ids[i : i + DETAIL_BATCH]
            batch_results = await asyncio.gather(
                *[_fetch_one_with_cache(client, mid) for mid in batch]
            )
            results.extend(batch_results)
            done = min(i + DETAIL_BATCH, len(movie_ids))
            print(f"  details {done}/{len(movie_ids)}")
    return results


async def _fetch_one_with_cache(client: httpx.AsyncClient, movie_id: int) -> dict:
    cache_path = RAW_DIR / f"movie_{movie_id}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    details = await get_movie_details(client, movie_id)
    cache_path.write_text(json.dumps(details), encoding="utf-8")
    return details


async def _load_into_db(details_list: list[dict]) -> int:
    loaded = 0
    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        for i, details in enumerate(details_list, start=1):
            await _upsert_movie(conn, details)
            loaded += 1
            if i % DB_COMMIT_BATCH == 0:
                await conn.commit()
                print(f"  committed {i}/{len(details_list)}")
        await conn.commit()
    return loaded


async def _executemany(
    conn: psycopg.AsyncConnection,
    sql: str,
    rows: list[tuple],
) -> None:
    if not rows:
        return
    async with conn.cursor() as cur:
        await cur.executemany(sql, rows)


async def _upsert_movie(conn: psycopg.AsyncConnection, m: dict) -> None:
    """Parse one TMDB movie dict and insert into all relevant tables."""
    release_year = int(m["release_date"][:4]) if m.get("release_date") else None

    await conn.execute(
        """
        INSERT INTO movies (id, title, release_year, overview, tagline, runtime, vote_average, raw)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (
            m["id"],
            m["title"],
            release_year,
            m.get("overview"),
            m.get("tagline"),
            m.get("runtime"),
            m.get("vote_average"),
            json.dumps(m),
        ),
    )

    genres = m.get("genres", [])
    if genres:
        await _executemany(
            conn,
            "INSERT INTO genres (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
            [(g["id"], g["name"]) for g in genres],
        )
        await _executemany(
            conn,
            "INSERT INTO movie_genres (movie_id, genre_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            [(m["id"], g["id"]) for g in genres],
        )

    keywords = m.get("keywords", {}).get("keywords", [])
    if keywords:
        await _executemany(
            conn,
            "INSERT INTO keywords (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
            [(k["id"], k["name"]) for k in keywords],
        )
        await _executemany(
            conn,
            "INSERT INTO movie_keywords (movie_id, keyword_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            [(m["id"], k["id"]) for k in keywords],
        )

    credits = m.get("credits", {})
    cast = credits.get("cast", [])[:10]
    if cast:
        await _executemany(
            conn,
            "INSERT INTO people (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
            [(c["id"], c["name"]) for c in cast],
        )
        await _executemany(
            conn,
            """
            INSERT INTO movie_people (movie_id, person_id, role, cast_order)
            VALUES (%s, %s, 'actor', %s) ON CONFLICT DO NOTHING
            """,
            [(m["id"], c["id"], c.get("order")) for c in cast],
        )

    crew_rows: list[tuple] = []
    for c in credits.get("crew", []):
        if c["job"] not in ("Director", "Writer", "Screenplay"):
            continue
        role = "director" if c["job"] == "Director" else "writer"
        crew_rows.append((c["id"], c["name"], m["id"], c["id"], role))
    if crew_rows:
        await _executemany(
            conn,
            "INSERT INTO people (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
            [(r[0], r[1]) for r in crew_rows],
        )
        await _executemany(
            conn,
            """
            INSERT INTO movie_people (movie_id, person_id, role)
            VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
            """,
            [(r[2], r[3], r[4]) for r in crew_rows],
        )
