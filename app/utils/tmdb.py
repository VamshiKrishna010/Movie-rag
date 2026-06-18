TMDB_POSTER_BASE = "https://image.tmdb.org/t/p/w342"
TMDB_BACKDROP_BASE = "https://image.tmdb.org/t/p/w780"


def poster_url(poster_path: str | None) -> str | None:
    return f"{TMDB_POSTER_BASE}{poster_path}" if poster_path else None


def backdrop_url(backdrop_path: str | None) -> str | None:
    return f"{TMDB_BACKDROP_BASE}{backdrop_path}" if backdrop_path else None
