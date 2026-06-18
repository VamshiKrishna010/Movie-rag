import asyncio
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings

TMDB_BASE = "https://api.themoviedb.org/3"
TIMEOUT = httpx.Timeout(15.0, connect=5.0)

# Self-throttle: TMDB allows ~50 req/sec but we'll be polite.
# A semaphore caps how many requests run concurrently.
_semaphore = asyncio.Semaphore(8)


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
)
async def _get(client: httpx.AsyncClient, path: str, params: dict | None = None) -> dict:
    """Single GET with retry on transient failures."""
    params = {**(params or {}), "api_key": settings.tmdb_api_key}
    async with _semaphore:
        resp = await client.get(f"{TMDB_BASE}{path}", params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()


async def discover_movies(client: httpx.AsyncClient, page: int) -> dict:
    """One page (20 movies) of TMDB's discover endpoint, sorted by vote_count desc."""
    return await _get(
        client,
        "/discover/movie",
        params={
            "sort_by": "vote_count.desc",
            "include_adult": "false",
            "language": "en-US",
            "page": page,
        },
    )


async def get_movie_details(client: httpx.AsyncClient, movie_id: int) -> dict:
    """Full movie data including credits and keywords in one call."""
    return await _get(
        client,
        f"/movie/{movie_id}",
        params={"append_to_response": "credits,keywords", "language": "en-US"},
    )