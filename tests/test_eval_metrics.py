import asyncio
import csv
import json
from types import SimpleNamespace

import pytest

from eval import mrr
from eval.metrics import (
    mean_reciprocal_rank,
    normalize_title,
    recall_at_k,
    reciprocal_rank_at_k,
)


def _chunk(movie_id: int, title: str, score: float = 0.5) -> SimpleNamespace:
    return SimpleNamespace(movie_id=movie_id, title=title, rrf_score=score)


def _item(
    *,
    item_id: str = "test_01",
    category: str = "factual",
    question: str = "Which movie is relevant?",
    relevant: list[str] | None = None,
) -> dict:
    return {
        "id": item_id,
        "category": category,
        "difficulty": "medium",
        "question": question,
        "ground_truth_movies": relevant or ["Relevant Movie"],
    }


def test_normalize_title_nfkc_casefolds_and_collapses_whitespace() -> None:
    assert normalize_title("  ＤＵＮＥ \n Part   Two  ") == "dune part two"


@pytest.mark.parametrize(
    ("retrieved", "relevant", "k", "expected"),
    [
        (["Inception", "Heat"], ["Inception"], 5, ("Inception", 1, 1.0)),
        (["Heat", "Inception"], ["Inception"], 5, ("Inception", 2, 0.5)),
        (["Heat"], ["Inception"], 5, (None, None, 0.0)),
        (["Heat", "Inception"], ["Inception"], 1, (None, None, 0.0)),
        (
            ["Heat", "Inception", "Memento"],
            ["Memento", "Inception"],
            5,
            ("Inception", 2, 0.5),
        ),
        (["  inception "], ["INCEPTION"], 5, ("  inception ", 1, 1.0)),
    ],
)
def test_reciprocal_rank_at_k(
    retrieved: list[str],
    relevant: list[str],
    k: int,
    expected: tuple[str | None, int | None, float],
) -> None:
    assert reciprocal_rank_at_k(retrieved, relevant, k) == expected


def test_reciprocal_rank_requires_positive_k() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        reciprocal_rank_at_k(["Inception"], ["Inception"], 0)


def test_reciprocal_rank_uses_exact_titles_not_substrings() -> None:
    assert reciprocal_rank_at_k(["Dune: Part Two"], ["Dune"], 5) == (
        None,
        None,
        0.0,
    )


def test_mean_reciprocal_rank() -> None:
    assert mean_reciprocal_rank([1.0, 0.5, 0.0]) == pytest.approx(0.5)


def test_mean_reciprocal_rank_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="at least one"):
        mean_reciprocal_rank([])


@pytest.mark.parametrize(
    ("retrieved", "relevant", "k", "expected"),
    [
        (["Inception"], ["Inception"], 5, 1.0),
        (["Inception"], ["Inception", "Memento"], 5, 0.5),
        (["Heat", "Memento"], ["Inception", "Memento"], 1, 0.0),
        (["INCEPTION", "Inception"], ["Inception"], 5, 1.0),
        (["Dune: Part Two"], ["Dune"], 5, 0.0),
    ],
)
def test_recall_at_k(
    retrieved: list[str],
    relevant: list[str],
    k: int,
    expected: float,
) -> None:
    assert recall_at_k(retrieved, relevant, k) == pytest.approx(expected)


def test_recall_at_k_requires_relevance_labels() -> None:
    with pytest.raises(ValueError, match="relevant title"):
        recall_at_k(["Inception"], [], 5)


@pytest.mark.parametrize(
    ("strategy", "retriever_attribute"),
    [
        ("hybrid", "retrieve"),
        ("dense", "retrieve_dense"),
        ("sparse", "retrieve_sparse"),
        ("routed", "retrieve_routed_for_eval"),
    ],
)
def test_evaluate_items_selects_strategy_and_preserves_rank_order(
    monkeypatch,
    strategy: str,
    retriever_attribute: str,
) -> None:
    calls: list[tuple[str, int]] = []

    async def fake_retriever(question: str, k: int):
        calls.append((question, k))
        return [
            _chunk(10, "Irrelevant Movie", 0.9),
            _chunk(20, "Relevant Movie", 0.8),
        ]

    monkeypatch.setattr(mrr, retriever_attribute, fake_retriever)
    item = _item()
    records = asyncio.run(mrr.evaluate_items([item], strategy=strategy, k=5))

    assert calls == [(item["question"], 5)]
    assert records[0]["matched_movie"] == "Relevant Movie"
    assert records[0]["first_relevant_rank"] == 2
    assert records[0]["reciprocal_rank"] == 0.5
    assert records[0]["recall_at_k"] == 1.0
    assert [movie["title"] for movie in json.loads(records[0]["retrieved_movies"])] == [
        "Irrelevant Movie",
        "Relevant Movie",
    ]


def test_resolve_retriever_supports_sparse() -> None:
    assert mrr.resolve_retriever("sparse") is mrr.retrieve_sparse


def test_resolve_retriever_supports_routed() -> None:
    assert mrr.resolve_retriever("routed") is mrr.retrieve_routed_for_eval


def test_evaluate_items_surfaces_retrieval_failure() -> None:
    async def failing_retriever(_question: str, _k: int):
        raise ConnectionError("database unavailable")

    with pytest.raises(RuntimeError, match="retrieval failed for 'test_01'"):
        asyncio.run(
            mrr.evaluate_items(
                [_item()],
                strategy="hybrid",
                k=5,
                retriever=failing_retriever,
            )
        )


def test_evaluate_items_runs_with_bounded_parallelism_and_preserves_order() -> None:
    active = 0
    max_active = 0

    async def concurrent_retriever(question: str, _k: int):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return [_chunk(1, "Relevant Movie")]

    items = [
        _item(item_id=f"item_{index}", question=f"Question {index}")
        for index in range(6)
    ]
    records = asyncio.run(
        mrr.evaluate_items(
            items,
            strategy="hybrid",
            k=5,
            workers=2,
            retriever=concurrent_retriever,
        )
    )

    assert max_active == 2
    assert [record["id"] for record in records] == [
        item["id"] for item in items
    ]


def test_evaluate_items_requires_positive_workers() -> None:
    with pytest.raises(ValueError, match="workers must be greater than zero"):
        asyncio.run(
            mrr.evaluate_items(
                [_item()],
                strategy="hybrid",
                k=5,
                workers=0,
            )
        )


def test_parser_accepts_worker_count() -> None:
    args = mrr.build_parser().parse_args(["--workers", "7"])

    assert args.workers == 7


def test_load_items_rejects_empty_ground_truth_movies(tmp_path) -> None:
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "bad_01",
                        "category": "factual",
                        "difficulty": "easy",
                        "question": "A question",
                        "ground_truth_movies": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="ground_truth_movies"):
        mrr.load_items(dataset_path)


def test_write_results_has_expected_fields_and_mean(tmp_path) -> None:
    records = [
        mrr.score_item(
            _item(item_id="one"),
            [_chunk(1, "Relevant Movie")],
            strategy="hybrid",
            k=5,
        ),
        mrr.score_item(
            _item(item_id="two"),
            [_chunk(2, "Other"), _chunk(1, "Relevant Movie")],
            strategy="hybrid",
            k=5,
        ),
        mrr.score_item(
            _item(item_id="three"),
            [_chunk(2, "Other")],
            strategy="hybrid",
            k=5,
        ),
    ]

    versioned, latest = mrr.write_results(
        records,
        strategy="hybrid",
        results_dir=tmp_path,
        timestamp="20260628_120000",
    )

    assert versioned.name == "mrr_hybrid_20260628_120000.csv"
    assert latest.name == "mrr_hybrid_latest.csv"
    assert versioned.read_text(encoding="utf-8") == latest.read_text(encoding="utf-8")

    with latest.open(encoding="utf-8", newline="") as result_file:
        rows = list(csv.DictReader(result_file))

    assert list(rows[0]) == mrr.CSV_FIELDS
    csv_mean = sum(float(row["reciprocal_rank"]) for row in rows) / len(rows)
    assert csv_mean == pytest.approx(0.5)
    csv_recall = sum(float(row["recall_at_k"]) for row in rows) / len(rows)
    assert csv_recall == pytest.approx(2 / 3)
