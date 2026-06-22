"""Endpoint coverage for the public catalog routes (health, genres, browse,
detail, title search). These hit a live Postgres seeded with movie data — the
same setup the auth tests assume. IDs are pulled from the API itself so the
tests don't hardcode TMDB ids."""


def test_health_ok(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_genres_public(client) -> None:
    # No Authorization header — /genres is intentionally public.
    response = client.get("/genres")
    assert response.status_code == 200
    genres = response.json()["genres"]
    assert len(genres) > 0
    first = genres[0]
    assert {"id", "name", "movie_count"} <= first.keys()
    assert first["movie_count"] >= 0


def test_browse_returns_paginated_movies(client) -> None:
    response = client.get("/movies/browse", params={"limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["limit"] == 5
    assert body["total"] > 0
    assert body["total_pages"] >= 1
    assert len(body["movies"]) <= 5
    movie = body["movies"][0]
    assert {"id", "title", "vote_average", "poster_url"} <= movie.keys()


def test_browse_pages_differ(client) -> None:
    page1 = client.get("/movies/browse", params={"limit": 3, "page": 1}).json()
    page2 = client.get("/movies/browse", params={"limit": 3, "page": 2}).json()
    ids1 = {m["id"] for m in page1["movies"]}
    ids2 = {m["id"] for m in page2["movies"]}
    assert ids1.isdisjoint(ids2)


def test_browse_genre_filter(client) -> None:
    genre_id = client.get("/genres").json()["genres"][0]["id"]
    response = client.get("/movies/browse", params={"genre_id": genre_id, "limit": 5})
    assert response.status_code == 200
    assert response.json()["total"] >= 0


def test_movie_detail(client) -> None:
    movie_id = client.get("/movies/browse", params={"limit": 1}).json()["movies"][0]["id"]
    response = client.get(f"/movies/{movie_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == movie_id
    assert isinstance(body["title"], str) and body["title"]
    for list_field in ("genres", "directors", "writers", "cast", "keywords"):
        assert isinstance(body[list_field], list)
    assert len(body["cast"]) <= 10


def test_movie_detail_not_found(client) -> None:
    response = client.get("/movies/999999999")
    assert response.status_code == 404


def test_search_empty_query_falls_back_to_browse(client) -> None:
    response = client.get("/movies/search", params={"q": "   "})
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == ""
    assert body["mode"] == "title"


def test_search_title_mode_is_public(client) -> None:
    # Short query resolves to title search, which needs no auth (unlike hybrid).
    response = client.get("/movies/search", params={"q": "the", "mode": "title"})
    assert response.status_code == 200
    assert response.json()["mode"] == "title"


def test_search_hybrid_mode_requires_auth(client) -> None:
    response = client.get("/movies/search", params={"q": "x", "mode": "hybrid"})
    assert response.status_code == 401
