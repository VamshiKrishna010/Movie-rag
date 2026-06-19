import json
import math

from psycopg.rows import dict_row

from app.db import get_connection


class MovieAdminError(Exception):
    pass


def _build_raw(poster_path: str | None, backdrop_path: str | None) -> str:
    payload: dict[str, str] = {}
    if poster_path:
        payload["poster_path"] = poster_path
    if backdrop_path:
        payload["backdrop_path"] = backdrop_path
    return json.dumps(payload)


async def get_stats() -> dict:
    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM users) AS user_count,
                    (SELECT COUNT(*) FROM movies) AS movie_count,
                    (SELECT COUNT(*) FROM chunks) AS chunk_count,
                    (SELECT COUNT(*) FROM genres) AS genre_count
                """
            )
            return await cur.fetchone()


async def list_movies(*, page: int, limit: int, q: str | None) -> dict:
    offset = (page - 1) * limit
    params: dict = {"limit": limit, "offset": offset}
    where = ""
    if q:
        where = "WHERE m.title ILIKE %(q)s"
        params["q"] = f"%{q}%"

    sql = f"""
    SELECT
      m.id,
      m.title,
      m.release_year,
      m.overview,
      m.tagline,
      m.runtime,
      m.vote_average,
      m.raw->>'poster_path' AS poster_path,
      m.raw->>'backdrop_path' AS backdrop_path,
      COUNT(*) OVER() AS total
    FROM movies m
    {where}
    ORDER BY m.id DESC
    OFFSET %(offset)s
    LIMIT %(limit)s;
    """

    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            rows = await cur.fetchall()

    total = int(rows[0]["total"]) if rows else 0
    total_pages = max(1, math.ceil(total / limit)) if total > 0 else 1
    movies = [{k: v for k, v in row.items() if k != "total"} for row in rows]
    return {
        "movies": movies,
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": total_pages,
    }


async def get_movie(movie_id: int) -> dict | None:
    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT
                  m.id,
                  m.title,
                  m.release_year,
                  m.overview,
                  m.tagline,
                  m.runtime,
                  m.vote_average,
                  m.raw->>'poster_path' AS poster_path,
                  m.raw->>'backdrop_path' AS backdrop_path
                FROM movies m
                WHERE m.id = %(movie_id)s
                """,
                {"movie_id": movie_id},
            )
            return await cur.fetchone()


async def create_movie(data: dict) -> dict:
    movie_id = data["id"]
    raw = _build_raw(data.get("poster_path"), data.get("backdrop_path"))

    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT id FROM movies WHERE id = %(id)s", {"id": movie_id})
            if await cur.fetchone():
                raise MovieAdminError("Movie id already exists")

            await cur.execute(
                """
                INSERT INTO movies (
                  id, title, release_year, overview, tagline, runtime, vote_average, raw
                )
                VALUES (
                  %(id)s, %(title)s, %(release_year)s, %(overview)s,
                  %(tagline)s, %(runtime)s, %(vote_average)s, %(raw)s::jsonb
                )
                RETURNING id, title, release_year, overview, tagline, runtime, vote_average
                """,
                {
                    "id": movie_id,
                    "title": data["title"],
                    "release_year": data.get("release_year"),
                    "overview": data.get("overview"),
                    "tagline": data.get("tagline"),
                    "runtime": data.get("runtime"),
                    "vote_average": data.get("vote_average"),
                    "raw": raw,
                },
            )
            row = await cur.fetchone()
            await conn.commit()

    result = dict(row)
    result["poster_path"] = data.get("poster_path")
    result["backdrop_path"] = data.get("backdrop_path")
    return result


async def update_movie(movie_id: int, data: dict) -> dict:
    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT id, raw FROM movies WHERE id = %(id)s", {"id": movie_id})
            existing = await cur.fetchone()
            if existing is None:
                raise MovieAdminError("Movie not found")

            raw_obj = existing["raw"] if isinstance(existing["raw"], dict) else {}
            if data.get("poster_path") is not None:
                raw_obj["poster_path"] = data["poster_path"]
            if data.get("backdrop_path") is not None:
                raw_obj["backdrop_path"] = data["backdrop_path"]

            await cur.execute(
                """
                UPDATE movies
                SET
                  title = %(title)s,
                  release_year = %(release_year)s,
                  overview = %(overview)s,
                  tagline = %(tagline)s,
                  runtime = %(runtime)s,
                  vote_average = %(vote_average)s,
                  raw = %(raw)s::jsonb
                WHERE id = %(id)s
                RETURNING id, title, release_year, overview, tagline, runtime, vote_average, raw
                """,
                {
                    "id": movie_id,
                    "title": data["title"],
                    "release_year": data.get("release_year"),
                    "overview": data.get("overview"),
                    "tagline": data.get("tagline"),
                    "runtime": data.get("runtime"),
                    "vote_average": data.get("vote_average"),
                    "raw": json.dumps(raw_obj),
                },
            )
            row = await cur.fetchone()
            await conn.commit()

    result = dict(row)
    raw = result.pop("raw") or {}
    if isinstance(raw, str):
        raw = json.loads(raw)
    result["poster_path"] = raw.get("poster_path")
    result["backdrop_path"] = raw.get("backdrop_path")
    return result
