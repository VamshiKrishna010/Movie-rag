import math
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row
from pydantic import BaseModel

from app.db import get_connection
from app.rag.retriever import retrieve_movie_rankings
from app.utils.tmdb import backdrop_url, poster_url

router = APIRouter()

SearchMode = Literal["auto", "title", "hybrid"]
_HYBRID_POOL_MAX = 100
_DEFAULT_LIMIT = 16
_GENRES_TTL_SEC = 300

_genres_cache: "GenresResponse | None" = None
_genres_cached_at: float = 0.0


class MovieOut(BaseModel):
    id: int
    title: str
    release_year: int | None
    overview: str | None
    vote_average: float | None
    poster_url: str | None


class PaginatedMoviesResponse(BaseModel):
    movies: list[MovieOut]
    page: int
    limit: int
    total: int
    total_pages: int


class SearchResponse(PaginatedMoviesResponse):
    query: str
    mode: Literal["title", "hybrid"]


class GenreOut(BaseModel):
    id: int
    name: str
    movie_count: int


class GenresResponse(BaseModel):
    genres: list[GenreOut]


class MovieDetailOut(BaseModel):
    id: int
    title: str
    release_year: int | None
    overview: str | None
    tagline: str | None
    runtime: int | None
    vote_average: float | None
    poster_url: str | None
    backdrop_url: str | None
    genres: list[str]
    directors: list[str]
    writers: list[str]
    cast: list[str]
    keywords: list[str]


def _truncate_overview(text: str | None, max_len: int = 150) -> str | None:
    if not text:
        return None
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _row_to_movie(row: dict) -> MovieOut:
    return MovieOut(
        id=row["id"],
        title=row["title"],
        release_year=row["release_year"],
        overview=_truncate_overview(row.get("overview")),
        vote_average=row.get("vote_average"),
        poster_url=poster_url(row.get("poster_path")),
    )


def _paginated(movies: list[MovieOut], page: int, limit: int, total: int) -> dict:
    total_pages = max(1, math.ceil(total / limit)) if total > 0 else 1
    return {
        "movies": movies,
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": total_pages,
    }


def _genre_join(genre_id: int | None) -> tuple[str, str]:
    if genre_id is None:
        return "", ""
    return (
        "JOIN movie_genres mg ON mg.movie_id = m.id AND mg.genre_id = %(genre_id)s",
        "JOIN movie_genres mg ON mg.movie_id = m.id AND mg.genre_id = %(genre_id)s",
    )


_GENRES_SQL = """
SELECT g.id, g.name, COUNT(mg.movie_id) AS movie_count
FROM genres g
JOIN movie_genres mg ON mg.genre_id = g.id
GROUP BY g.id, g.name
ORDER BY g.name;
"""

_DETAIL_SQL = """
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
    (
        SELECT array_agg(g.name ORDER BY g.name)
        FROM movie_genres mg
        JOIN genres g ON g.id = mg.genre_id
        WHERE mg.movie_id = m.id
    ) AS genres,
    (
        SELECT array_agg(p.name ORDER BY p.name)
        FROM movie_people mp
        JOIN people p ON p.id = mp.person_id
        WHERE mp.movie_id = m.id AND mp.role = 'director'
    ) AS directors,
    (
        SELECT array_agg(p.name ORDER BY p.name)
        FROM movie_people mp
        JOIN people p ON p.id = mp.person_id
        WHERE mp.movie_id = m.id AND mp.role = 'writer'
    ) AS writers,
    (
        SELECT array_agg(sub.name ORDER BY sub.ord NULLS LAST)
        FROM (
            SELECT p.name, mp.cast_order AS ord
            FROM movie_people mp
            JOIN people p ON p.id = mp.person_id
            WHERE mp.movie_id = m.id AND mp.role = 'actor'
            ORDER BY mp.cast_order NULLS LAST
            LIMIT 10
        ) sub
    ) AS cast_list,
    (
        SELECT array_agg(sub.name ORDER BY sub.name)
        FROM (
            SELECT k.name
            FROM movie_keywords mk
            JOIN keywords k ON k.id = mk.keyword_id
            WHERE mk.movie_id = m.id
            ORDER BY k.name
            LIMIT 15
        ) sub
    ) AS keywords
FROM movies m
WHERE m.id = %(movie_id)s;
"""

_FETCH_BY_IDS_SQL = """
SELECT
  m.id,
  m.title,
  m.release_year,
  m.overview,
  m.vote_average,
  m.raw->>'poster_path' AS poster_path
FROM movies m
WHERE m.id = ANY(%(ids)s);
"""


async def _fetch_browse(
    page: int,
    limit: int,
    genre_id: int | None,
) -> PaginatedMoviesResponse:
    join, _count_join = _genre_join(genre_id)
    offset = (page - 1) * limit
    params: dict = {"limit": limit, "offset": offset}
    if genre_id is not None:
        params["genre_id"] = genre_id

    browse_sql = f"""
    SELECT
      m.id,
      m.title,
      m.release_year,
      m.overview,
      m.vote_average,
      m.raw->>'poster_path' AS poster_path,
      COUNT(*) OVER() AS total
    FROM movies m
    {join}
    ORDER BY m.vote_average DESC NULLS LAST
    OFFSET %(offset)s
    LIMIT %(limit)s;
    """

    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(browse_sql, params)
            rows = await cur.fetchall()

    total = rows[0]["total"] if rows else 0
    return PaginatedMoviesResponse(
        **_paginated([_row_to_movie(r) for r in rows], page, limit, total)
    )


async def _fetch_title_search(
    q: str,
    page: int,
    limit: int,
    genre_id: int | None,
) -> PaginatedMoviesResponse:
    join, _count_join = _genre_join(genre_id)
    offset = (page - 1) * limit
    params: dict = {"pattern": f"%{q}%", "limit": limit, "offset": offset}
    if genre_id is not None:
        params["genre_id"] = genre_id

    search_sql = f"""
    SELECT
      m.id,
      m.title,
      m.release_year,
      m.overview,
      m.vote_average,
      m.raw->>'poster_path' AS poster_path,
      COUNT(*) OVER() AS total
    FROM movies m
    {join}
    WHERE m.title ILIKE %(pattern)s
    ORDER BY m.vote_average DESC NULLS LAST
    OFFSET %(offset)s
    LIMIT %(limit)s;
    """

    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(search_sql, params)
            rows = await cur.fetchall()

    total = rows[0]["total"] if rows else 0
    return PaginatedMoviesResponse(
        **_paginated([_row_to_movie(r) for r in rows], page, limit, total)
    )


async def _filter_ids_by_genre(movie_ids: list[int], genre_id: int | None) -> list[int]:
    if genre_id is None or not movie_ids:
        return movie_ids

    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT movie_id FROM movie_genres
                WHERE genre_id = %(genre_id)s AND movie_id = ANY(%(ids)s)
                """,
                {"genre_id": genre_id, "ids": movie_ids},
            )
            allowed = {r["movie_id"] for r in await cur.fetchall()}

    return [mid for mid in movie_ids if mid in allowed]


async def _fetch_hybrid_search(
    q: str,
    page: int,
    limit: int,
    genre_id: int | None,
) -> PaginatedMoviesResponse:
    try:
        rankings = await retrieve_movie_rankings(q, k=_HYBRID_POOL_MAX)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {e}") from e

    if not rankings:
        return PaginatedMoviesResponse(**_paginated([], page, limit, 0))

    ranked_ids = [r.movie_id for r in rankings]
    if genre_id is not None:
        ranked_ids = await _filter_ids_by_genre(ranked_ids, genre_id)
    total = len(ranked_ids)

    offset = (page - 1) * limit
    page_ids = ranked_ids[offset : offset + limit]

    if not page_ids:
        return PaginatedMoviesResponse(**_paginated([], page, limit, total))

    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_FETCH_BY_IDS_SQL, {"ids": page_ids})
            rows = await cur.fetchall()

    by_id = {r["id"]: r for r in rows}
    movies = [_row_to_movie(by_id[mid]) for mid in page_ids if mid in by_id]

    return PaginatedMoviesResponse(**_paginated(movies, page, limit, total))


def _resolve_mode(q: str, mode: SearchMode) -> Literal["title", "hybrid"]:
    if mode == "title":
        return "title"
    if mode == "hybrid":
        return "hybrid"
    words = q.split()
    if len(words) <= 2 and len(q) <= 30:
        return "title"
    return "hybrid"


def _list_or_empty(value) -> list[str]:
    if not value:
        return []
    return list(value)


@router.get("/genres", response_model=GenresResponse)
async def list_genres() -> GenresResponse:
    global _genres_cache, _genres_cached_at
    now = time.monotonic()
    if _genres_cache is not None and (now - _genres_cached_at) < _GENRES_TTL_SEC:
        return _genres_cache

    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_GENRES_SQL)
            rows = await cur.fetchall()
    _genres_cache = GenresResponse(
        genres=[
            GenreOut(id=r["id"], name=r["name"], movie_count=r["movie_count"])
            for r in rows
        ]
    )
    _genres_cached_at = now
    return _genres_cache


@router.get("/movies/browse", response_model=PaginatedMoviesResponse)
async def browse_movies(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=16),
    genre_id: int | None = Query(default=None),
) -> PaginatedMoviesResponse:
    return await _fetch_browse(page, limit, genre_id)


@router.get("/movies/search", response_model=SearchResponse)
async def search_movies(
    q: str = Query(default="", max_length=250),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=16),
    genre_id: int | None = Query(default=None),
    mode: SearchMode = Query(default="auto"),
) -> SearchResponse:
    q = q.strip()
    if not q:
        result = await _fetch_browse(page, limit, genre_id)
        return SearchResponse(query="", mode="title", **result.model_dump())

    resolved = _resolve_mode(q, mode)
    if resolved == "title":
        result = await _fetch_title_search(q, page, limit, genre_id)
    else:
        result = await _fetch_hybrid_search(q, page, limit, genre_id)

    return SearchResponse(query=q, mode=resolved, **result.model_dump())


@router.get("/movies/{movie_id}", response_model=MovieDetailOut)
async def get_movie_detail(movie_id: int) -> MovieDetailOut:
    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_DETAIL_SQL, {"movie_id": movie_id})
            row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Movie not found")

    cast = _list_or_empty(row.get("cast_list"))[:10]

    return MovieDetailOut(
        id=row["id"],
        title=row["title"],
        release_year=row["release_year"],
        overview=row.get("overview"),
        tagline=row.get("tagline"),
        runtime=row.get("runtime"),
        vote_average=row.get("vote_average"),
        poster_url=poster_url(row.get("poster_path")),
        backdrop_url=backdrop_url(row.get("backdrop_path")),
        genres=_list_or_empty(row.get("genres")),
        directors=_list_or_empty(row.get("directors")),
        writers=_list_or_empty(row.get("writers")),
        cast=cast,
        keywords=_list_or_empty(row.get("keywords")),
    )
