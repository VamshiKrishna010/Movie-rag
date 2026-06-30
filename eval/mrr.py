"""Standalone MRR@K evaluation for the movie retrievers.

Run from the project root:

    python -m eval.mrr --strategy hybrid --k 5
    python -m eval.mrr --strategy dense --k 5
    python -m eval.mrr --strategy sparse --k 5
    python -m eval.mrr --strategy routed --k 5
    python -m eval.mrr --strategy hybrid --k 5 --workers 4
"""

import argparse
import asyncio
import csv
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Awaitable, Callable, Sequence

from app.db import get_connection
from app.rag.retriever import RetrievedChunk, retrieve, retrieve_dense, retrieve_routed
from app.rag.sparse import build_loose_tsquery
from eval.metrics import mean_reciprocal_rank, recall_at_k, reciprocal_rank_at_k
from psycopg.rows import dict_row


HERE = Path(__file__).parent
DATASET_PATH = HERE / "dataset.json"
RESULTS_DIR = HERE / "results"
DEFAULT_K = 10
DEFAULT_WORKERS = 4
STRATEGIES = ("hybrid", "dense", "sparse", "routed")

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
        description="Evaluate dense, sparse, or hybrid movie retrieval with MRR@K.",
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
    parser.add_argument(
        "--workers",
        type=_positive_int,
        default=DEFAULT_WORKERS,
        help=(
            "maximum concurrent retrievals; use 1 for sequential evaluation "
            f"(default: {DEFAULT_WORKERS})"
        ),
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
    if strategy == "sparse":
        return retrieve_sparse
    if strategy == "routed":
        return retrieve_routed_for_eval
    raise ValueError(f"unsupported strategy: {strategy}")


async def retrieve_routed_for_eval(question: str, k: int = 10) -> list[RetrievedChunk]:
    chunks, _route = await retrieve_routed(question, k=k)
    return chunks


async def retrieve_sparse(question: str, k: int = 10) -> list[RetrievedChunk]:
    """Sparse-only baseline: enriched lexical search, deduped by movie."""
    sql = """
    WITH query_terms AS (
      SELECT
        websearch_to_tsquery('english', %(question)s) AS strict_q,
        CASE
          WHEN %(loose_tsquery)s = '' THEN NULL
          ELSE to_tsquery('english', %(loose_tsquery)s)
        END AS loose_q,
        ' ' || trim(
          regexp_replace(lower(%(question)s), '[^[:alnum:]]+', ' ', 'g')
        ) || ' ' AS query_norm
    ),
    mentioned_titles AS (
      SELECT m.id
      FROM movies m, query_terms qt
      CROSS JOIN LATERAL (
        SELECT trim(
          regexp_replace(lower(m.title), '[^[:alnum:]]+', ' ', 'g')
        ) AS title_norm
      ) n
      WHERE length(n.title_norm) >= 3
        AND qt.query_norm LIKE '%% ' || n.title_norm || ' %%'
    ),
    mentioned_people AS (
      SELECT p.id
      FROM people p, query_terms qt
      CROSS JOIN LATERAL (
        SELECT trim(
          regexp_replace(lower(p.name), '[^[:alnum:]]+', ' ', 'g')
        ) AS person_norm
      ) n
      WHERE length(n.person_norm) >= 5
        AND qt.query_norm LIKE '%% ' || n.person_norm || ' %%'
    ),
    mentioned_title_directors AS (
      SELECT DISTINCT mp.person_id
      FROM mentioned_titles mt
      JOIN movie_people mp
        ON mp.movie_id = mt.id
       AND mp.role = 'director'
    ),
    metadata_movies AS (
      SELECT
        movie_id,
        max(title_match) AS title_match,
        sum(person_matches) AS person_matches,
        sum(director_matches) AS director_matches
      FROM (
        SELECT
          id AS movie_id,
          1 AS title_match,
          0 AS person_matches,
          0 AS director_matches
        FROM mentioned_titles
        UNION ALL
        SELECT
          mp.movie_id,
          0 AS title_match,
          count(DISTINCT mp.person_id) AS person_matches,
          0 AS director_matches
        FROM movie_people mp
        WHERE mp.person_id IN (SELECT id FROM mentioned_people)
        GROUP BY mp.movie_id
        UNION ALL
        SELECT
          mp.movie_id,
          0 AS title_match,
          0 AS person_matches,
          count(DISTINCT mp.person_id) AS director_matches
        FROM movie_people mp
        WHERE mp.role = 'director'
          AND mp.person_id IN (SELECT person_id FROM mentioned_title_directors)
        GROUP BY mp.movie_id
      ) matches
      GROUP BY movie_id
    ),
    fts_chunks AS (
      SELECT
        c.id AS chunk_id,
        (
          4.0 * ts_rank_cd(c.search_vector, qt.strict_q)
          + COALESCE(ts_rank_cd(c.search_vector, qt.loose_q), 0)
        ) AS fts_score
      FROM chunks c
      CROSS JOIN query_terms qt
      WHERE c.search_vector @@ qt.strict_q
         OR (qt.loose_q IS NOT NULL AND c.search_vector @@ qt.loose_q)
      ORDER BY fts_score DESC, c.id
      LIMIT %(fts_pool)s
    ),
    candidate_chunks AS (
      SELECT chunk_id FROM fts_chunks
      UNION
      SELECT c.id AS chunk_id
      FROM chunks c
      JOIN metadata_movies mm ON mm.movie_id = c.movie_id
    ),
    ranked AS (
      SELECT
        c.id AS chunk_id,
        c.movie_id,
        m.title,
        m.release_year,
        c.content AS chunk_text,
        ts_rank_cd(c.search_vector, qt.strict_q) AS strict_score,
        COALESCE(ts_rank_cd(c.search_vector, qt.loose_q), 0) AS loose_score,
        COALESCE(mm.title_match, 0) AS title_match,
        COALESCE(mm.person_matches, 0) AS person_matches,
        COALESCE(mm.director_matches, 0) AS director_matches,
        (
          4.0 * ts_rank_cd(c.search_vector, qt.strict_q)
          + COALESCE(ts_rank_cd(c.search_vector, qt.loose_q), 0)
          + 3.0 * COALESCE(mm.title_match, 0)
          + 1.8 * COALESCE(mm.person_matches, 0)
          + 1.2 * COALESCE(mm.director_matches, 0)
          + CASE c.chunk_type
              WHEN 'themes' THEN 0.05
              WHEN 'plot' THEN 0.03
              ELSE 0.01
            END
        ) AS score,
        ROW_NUMBER() OVER (
          PARTITION BY c.movie_id
          ORDER BY
            (
              4.0 * ts_rank_cd(c.search_vector, qt.strict_q)
              + COALESCE(ts_rank_cd(c.search_vector, qt.loose_q), 0)
              + 3.0 * COALESCE(mm.title_match, 0)
              + 1.8 * COALESCE(mm.person_matches, 0)
              + 1.2 * COALESCE(mm.director_matches, 0)
              + CASE c.chunk_type
                  WHEN 'themes' THEN 0.05
                  WHEN 'plot' THEN 0.03
                  ELSE 0.01
                END
            ) DESC,
            COALESCE(mm.title_match, 0) DESC,
            COALESCE(mm.person_matches, 0) DESC,
            COALESCE(mm.director_matches, 0) DESC,
            ts_rank_cd(c.search_vector, qt.strict_q) DESC,
            COALESCE(ts_rank_cd(c.search_vector, qt.loose_q), 0) DESC,
            CASE c.chunk_type
              WHEN 'themes' THEN 0
              WHEN 'plot' THEN 1
              ELSE 2
            END,
            c.id
        ) AS movie_rank
      FROM candidate_chunks cc
      JOIN chunks c ON c.id = cc.chunk_id
      JOIN movies m ON m.id = c.movie_id
      CROSS JOIN query_terms qt
      LEFT JOIN metadata_movies mm ON mm.movie_id = c.movie_id
    )
    SELECT
      chunk_id,
      movie_id,
      title,
      release_year,
      chunk_text,
      score AS rrf_score
    FROM ranked
    WHERE movie_rank = 1
    ORDER BY
      score DESC,
      title_match DESC,
      person_matches DESC,
      director_matches DESC,
      strict_score DESC,
      loose_score DESC,
      chunk_id
    LIMIT %(k)s;
    """
    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                sql,
                {
                    "question": question,
                    "loose_tsquery": build_loose_tsquery(question),
                    "fts_pool": max(k * 80, 200),
                    "k": k,
                },
            )
            results = await cur.fetchall()
    return [
        RetrievedChunk(
            chunk_id=row["chunk_id"],
            movie_id=row["movie_id"],
            title=row["title"],
            release_year=row["release_year"],
            chunk_text=row["chunk_text"],
            rrf_score=float(row["rrf_score"]),
        )
        for row in results
    ]


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
    workers: int = DEFAULT_WORKERS,
    retriever: Retriever | None = None,
) -> list[dict[str, Any]]:
    if k <= 0:
        raise ValueError("k must be greater than zero")
    if workers <= 0:
        raise ValueError("workers must be greater than zero")

    selected_retriever = retriever or resolve_retriever(strategy)
    semaphore = asyncio.Semaphore(workers)
    records: list[dict[str, Any] | None] = [None] * len(items)

    async def evaluate_one(index: int, item: dict[str, Any]) -> None:
        async with semaphore:
            print(
                f"[{index + 1:>3}/{len(items)}] "
                f"{item['id']:>8}  {item['question'][:60]}"
            )
            try:
                chunks = await selected_retriever(item["question"], k)
            except Exception as exc:
                raise RuntimeError(
                    f"retrieval failed for {item['id']!r}: {item['question']}"
                ) from exc
            records[index] = score_item(item, chunks, strategy=strategy, k=k)

    await asyncio.gather(
        *(evaluate_one(index, item) for index, item in enumerate(items))
    )
    return [record for record in records if record is not None]


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
    workers: int = DEFAULT_WORKERS,
    dataset_path: Path = DATASET_PATH,
    results_dir: Path = RESULTS_DIR,
) -> list[dict[str, Any]]:
    items = load_items(dataset_path)
    print(f"Loaded {len(items)} eval items from {dataset_path.name}")
    print(f"Evaluating {strategy} retrieval at k={k} with {workers} workers\n")

    records = await evaluate_items(
        items,
        strategy=strategy,
        k=k,
        workers=workers,
    )
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
        asyncio.run(
            run(
                strategy=args.strategy,
                k=args.k,
                workers=args.workers,
            )
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"MRR evaluation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(main())
