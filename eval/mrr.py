"""Standalone MRR@K evaluation for the movie retrievers.

Run from the project root:

    python -m eval.mrr --strategy hybrid --k 5
    python -m eval.mrr --strategy dense --k 5
"""

import argparse
import asyncio
import csv
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Awaitable, Callable, Sequence

from app.rag.retriever import RetrievedChunk, retrieve, retrieve_dense
from eval.metrics import mean_reciprocal_rank, recall_at_k, reciprocal_rank_at_k


HERE = Path(__file__).parent
DATASET_PATH = HERE / "dataset.json"
RESULTS_DIR = HERE / "results"
DEFAULT_K = 10
STRATEGIES = ("hybrid", "dense")

Retriever = Callable[[str, int], Awaitable[list[RetrievedChunk]]]

CSV_FIELDS = [
    "id",
    "category",
    "difficulty",
    "question",
    "strategy",
    "k",
    "relevant_movies",
    "retrieved_movies",
    "matched_movie",
    "first_relevant_rank",
    "reciprocal_rank",
    "recall_at_k",
]


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate dense or hybrid movie retrieval with MRR@K.",
    )
    parser.add_argument(
        "--strategy",
        choices=STRATEGIES,
        default="hybrid",
        help="retrieval strategy to evaluate (default: hybrid)",
    )
    parser.add_argument(
        "--k",
        type=_positive_int,
        default=DEFAULT_K,
        help=f"retrieval cutoff (default: {DEFAULT_K})",
    )
    return parser


def load_items(dataset_path: Path = DATASET_PATH) -> list[dict[str, Any]]:
    with dataset_path.open(encoding="utf-8") as dataset_file:
        dataset = json.load(dataset_file)

    items = dataset.get("items") if isinstance(dataset, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError(f"{dataset_path} must contain a non-empty 'items' list")

    for index, item in enumerate(items):
        _validate_item(item, index)
    return items


def _validate_item(item: Any, index: int) -> None:
    if not isinstance(item, dict):
        raise ValueError(f"dataset item {index} must be an object")

    item_id = item.get("id", f"index {index}")
    for field in ("id", "category", "difficulty", "question"):
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"dataset item {item_id!r} needs a non-empty {field!r}")

    relevant = item.get("ground_truth_movies")
    if (
        not isinstance(relevant, list)
        or not relevant
        or any(not isinstance(title, str) or not title.strip() for title in relevant)
    ):
        raise ValueError(
            f"dataset item {item_id!r} needs non-empty string "
            "'ground_truth_movies'"
        )


def resolve_retriever(strategy: str) -> Retriever:
    if strategy == "hybrid":
        return retrieve
    if strategy == "dense":
        return retrieve_dense
    raise ValueError(f"unsupported strategy: {strategy}")


def score_item(
    item: dict[str, Any],
    chunks: Sequence[RetrievedChunk],
    *,
    strategy: str,
    k: int,
) -> dict[str, Any]:
    retrieved_titles = [chunk.title for chunk in chunks]
    matched_movie, first_rank, reciprocal_rank = reciprocal_rank_at_k(
        retrieved_titles,
        item["ground_truth_movies"],
        k,
    )
    recall = recall_at_k(retrieved_titles, item["ground_truth_movies"], k)
    retrieved_movies = [
        {
            "movie_id": chunk.movie_id,
            "title": chunk.title,
            "score": float(chunk.rrf_score),
        }
        for chunk in chunks[:k]
    ]

    return {
        "id": item["id"],
        "category": item["category"],
        "difficulty": item["difficulty"],
        "question": item["question"],
        "strategy": strategy,
        "k": k,
        "relevant_movies": json.dumps(
            item["ground_truth_movies"],
            ensure_ascii=False,
        ),
        "retrieved_movies": json.dumps(retrieved_movies, ensure_ascii=False),
        "matched_movie": matched_movie or "",
        "first_relevant_rank": first_rank if first_rank is not None else "",
        "reciprocal_rank": reciprocal_rank,
        "recall_at_k": recall,
    }


async def evaluate_items(
    items: Sequence[dict[str, Any]],
    *,
    strategy: str,
    k: int,
    retriever: Retriever | None = None,
) -> list[dict[str, Any]]:
    if k <= 0:
        raise ValueError("k must be greater than zero")

    selected_retriever = retriever or resolve_retriever(strategy)
    records: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        print(f"[{index:>2}/{len(items)}] {item['id']:>8}  {item['question'][:60]}")
        try:
            chunks = await selected_retriever(item["question"], k)
        except Exception as exc:
            raise RuntimeError(
                f"retrieval failed for {item['id']!r}: {item['question']}"
            ) from exc
        records.append(score_item(item, chunks, strategy=strategy, k=k))
    return records


def write_results(
    records: Sequence[dict[str, Any]],
    *,
    strategy: str,
    results_dir: Path = RESULTS_DIR,
    timestamp: str | None = None,
) -> tuple[Path, Path]:
    if not records:
        raise ValueError("cannot write an empty evaluation result")

    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    versioned = results_dir / f"mrr_{strategy}_{stamp}.csv"
    latest = results_dir / f"mrr_{strategy}_latest.csv"

    for path in (versioned, latest):
        with path.open("w", encoding="utf-8", newline="") as result_file:
            writer = csv.DictWriter(result_file, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(records)

    return versioned, latest


def _print_group_summary(
    records: Sequence[dict[str, Any]],
    *,
    group_field: str,
    heading: str,
    k: int,
) -> None:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record[group_field], []).append(record)

    print(f"\n{heading}")
    print("=" * 55)
    print(f"{group_field:<20} {'MRR@' + str(k):>10} {'Recall@' + str(k):>12}")
    for group, group_records in grouped.items():
        mrr = mean_reciprocal_rank(
            float(record["reciprocal_rank"]) for record in group_records
        )
        recall = sum(
            float(record["recall_at_k"]) for record in group_records
        ) / len(group_records)
        print(f"{group:<20} {mrr:>10.3f} {recall:>12.3f}")


def print_summary(
    records: Sequence[dict[str, Any]],
    *,
    k: int,
) -> tuple[float, float]:
    if not records:
        raise ValueError("cannot summarize an empty evaluation result")

    _print_group_summary(
        records,
        group_field="category",
        heading=f"MRR@{k} AND RECALL@{k} BY CATEGORY",
        k=k,
    )
    _print_group_summary(
        records,
        group_field="difficulty",
        heading=f"MRR@{k} AND RECALL@{k} BY DIFFICULTY",
        k=k,
    )

    overall_mrr = mean_reciprocal_rank(
        float(record["reciprocal_rank"]) for record in records
    )
    overall_recall = sum(
        float(record["recall_at_k"]) for record in records
    ) / len(records)
    print("\nOVERALL")
    print("=" * 55)
    print(f"{'MRR@' + str(k):<20} {overall_mrr:.3f}")
    print(f"{'Recall@' + str(k):<20} {overall_recall:.3f}")
    return overall_mrr, overall_recall


async def run(
    *,
    strategy: str,
    k: int,
    dataset_path: Path = DATASET_PATH,
    results_dir: Path = RESULTS_DIR,
) -> list[dict[str, Any]]:
    items = load_items(dataset_path)
    print(f"Loaded {len(items)} eval items from {dataset_path.name}")
    print(f"Evaluating {strategy} retrieval at k={k}\n")

    records = await evaluate_items(items, strategy=strategy, k=k)
    versioned, latest = write_results(
        records,
        strategy=strategy,
        results_dir=results_dir,
    )
    print_summary(records, k=k)
    print(f"\nFull results: {versioned}")
    print(f"Latest alias: {latest}")
    return records


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        asyncio.run(run(strategy=args.strategy, k=args.k))
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"MRR evaluation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(main())
