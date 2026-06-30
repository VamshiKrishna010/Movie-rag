from app.rag.routing import classify_query, route_query


def test_routes_thematic_queries_to_dense() -> None:
    route = route_query("Movies about dreams within dreams")

    assert route.category == "thematic"
    assert route.strategy == "dense"


def test_routes_relational_queries_to_sparse() -> None:
    route = route_query("Which movies feature both Leonardo DiCaprio and Tom Hardy?")

    assert route.category == "relational"
    assert route.strategy == "sparse"


def test_routes_comparative_queries_to_sparse_for_recall() -> None:
    route = route_query("Compare organized crime in The Godfather and GoodFellas")

    assert route.category == "comparative"
    assert route.strategy == "sparse"


def test_routes_factual_queries_to_sparse() -> None:
    route = route_query("Who directed Inception?")

    assert route.category == "factual"
    assert route.strategy == "sparse"


def test_routes_unknown_queries_to_hybrid() -> None:
    route = route_query("surreal neon city mood")

    assert classify_query("surreal neon city mood") == "unknown"
    assert route.strategy == "hybrid"
