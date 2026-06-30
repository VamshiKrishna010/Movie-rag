from app.ingest.chunker import _chunk_records_for_row


def _movie_row(**overrides):
    row = {
        "id": 1,
        "title": "Example Movie",
        "release_year": 2024,
        "overview": (
            "A lonely android follows dreams through an artificial reality "
            "while planning a citywide heist."
        ),
        "tagline": "Every clue compiles.",
        "directors": ["Ava Director"],
        "writers": ["Wes Writer", "Nia Writer", "Lee Writer", "Pat Extra"],
        "cast_list": ["Casey Lead", "Morgan Co-Star"],
        "genres": ["Mystery", "Science Fiction"],
        "keywords": ["android", "dream", "heist", "identity"],
        "existing_chunk_types": [],
    }
    row.update(overrides)
    return row


def test_chunk_records_include_full_plot_and_theme_chunks() -> None:
    records = _chunk_records_for_row(_movie_row())

    by_type = {record.chunk_type: record for record in records}

    assert set(by_type) == {"full", "plot", "themes"}
    assert "Directed by Ava Director." in by_type["full"].content
    assert "Plot summary: A lonely android follows dreams" in by_type["full"].content
    assert "Movie: Example Movie (2024)." in by_type["plot"].content
    assert "Themes and story keywords: android, dream, heist, identity." in by_type["plot"].content
    assert "Themes: dreams and reality" in by_type["themes"].content
    assert "artificial reality and control" in by_type["themes"].content
    assert "artificial intelligence and robots" in by_type["themes"].content
    assert "heist plan" in by_type["themes"].content
    assert "Theme search phrases:" in by_type["themes"].content
    assert "dreams within dreams" in by_type["themes"].content
    assert "controlled reality" in by_type["themes"].content
    assert "artificial intelligence developing consciousness" in by_type["themes"].content
    assert "multi-step plan" in by_type["themes"].content
    assert "TMDB keywords: android, dream, heist, identity." in by_type["themes"].content


def test_chunk_records_only_emit_missing_chunk_types() -> None:
    records = _chunk_records_for_row(_movie_row(existing_chunk_types=["full", "plot"]))

    assert [record.chunk_type for record in records] == ["themes"]
