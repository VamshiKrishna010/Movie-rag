"""
Movie-RAG evaluation runner.

For each Q/A pair in eval/dataset.json:
  1. POST the question to the live /query endpoint
  2. Collect the answer + retrieved contexts
  3. Score with Ragas (faithfulness, answer relevance, context precision, context recall)
  4. Compute a deterministic movie-recall sanity check (no LLM)
  5. Dump per-question CSV + print category summary

Run from project root, with the FastAPI app running on :8000 in another terminal:

    python -m eval.run
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd
from datasets import Dataset

# Must come first: installs the vertexai stub before ragas's broken import runs.
from eval.ragas_config import JUDGE_LLM, JUDGE_EMBEDDER

from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
)

# ---- Paths -------------------------------------------------------------------
HERE = Path(__file__).parent
DATASET_PATH = HERE / "dataset.json"
RESULTS_DIR = HERE / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# ---- API ---------------------------------------------------------------------
API_URL = "http://localhost:8000/query"
TIMEOUT = httpx.Timeout(120.0, connect=10.0)  # Groq generation can take a while
TOP_K = 5


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Hit /query for every question
# ─────────────────────────────────────────────────────────────────────────────

async def query_api(client: httpx.AsyncClient, question: str) -> tuple[str, list[str]]:
    """Hit /query and extract (answer, contexts).

    Response shape (your actual /query):
        {
            "answer": "...",
            "retrieved": [
                {"chunk_text": "...", "title": "...", ...},
                ...
            ]
        }
    `include_chunks: true` is required — without it the API omits chunk_text.
    """
    resp = await client.post(
        API_URL,
        json={"question": question, "k": TOP_K, "include_chunks": True},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()

    answer = data["answer"]
    contexts = [src["chunk_text"] for src in data["retrieved"]]
    return answer, contexts


async def collect_predictions(items: list[dict]) -> list[dict]:
    """Run all 25 questions through /query, return enriched records."""
    async with httpx.AsyncClient() as client:
        results = []
        for i, item in enumerate(items, 1):
            preview = item["question"][:60]
            print(f"  [{i:>2}/{len(items)}] {item['id']:>8}  {preview}")
            try:
                answer, contexts = await query_api(client, item["question"])
            except Exception as e:
                # Print exception type so silent failures are diagnosable.
                print(f"           ⚠️  failed: {type(e).__name__}: {e}")
                answer, contexts = "", []
            results.append({
                "id": item["id"],
                "category": item["category"],
                "question": item["question"],
                "answer": answer,
                "contexts": contexts,
                "ground_truth": item["ground_truth_answer"],
                "ground_truth_movies": item["ground_truth_movies"],
            })
        return results


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Score with Ragas
# ─────────────────────────────────────────────────────────────────────────────

def run_ragas(records: list[dict]) -> pd.DataFrame:
    """Score all records with Ragas. Returns one row per question."""
    ds = Dataset.from_list([
        {
            "question":     r["question"],
            "answer":       r["answer"],
            "contexts":     r["contexts"],
            "ground_truth": r["ground_truth"],
        }
        for r in records
    ])

    result = evaluate(
        dataset=ds,
        metrics=[
            faithfulness,         # are answer claims supported by contexts?
            answer_relevancy,     # does the answer address the question?
            context_precision,    # are top-ranked contexts relevant?
            context_recall,       # did we find everything needed?
        ],
        llm=JUDGE_LLM,
        embeddings=JUDGE_EMBEDDER,
    )
    df = result.to_pandas()

    # Attach id + category so we can group in the summary
    df["id"] = [r["id"] for r in records]
    df["category"] = [r["category"] for r in records]
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — Deterministic sanity-check: did we retrieve the expected movies?
# ─────────────────────────────────────────────────────────────────────────────

def compute_movie_recall(records: list[dict]) -> list[float]:
    """For each question, what fraction of ground_truth_movies appear (by
    case-insensitive title substring) in the concatenated retrieved contexts?

    This is a cheap, deterministic check — no LLM involved. If Ragas gives
    weird context_precision scores, this number tells you the truth about
    whether the expected movies even made it into context.
    """
    recalls = []
    for r in records:
        gt = r["ground_truth_movies"]
        if not gt:
            recalls.append(0.0)
            continue
        joined = " ".join(r["contexts"]).lower()
        hits = sum(1 for m in gt if m.lower() in joined)
        recalls.append(hits / len(gt))
    return recalls


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — Summary
# ─────────────────────────────────────────────────────────────────────────────

METRIC_COLS = [
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
    "movie_recall",     # our deterministic one
]


def print_summary(df: pd.DataFrame) -> None:
    print("\n" + "=" * 80)
    print("PER-CATEGORY MEANS")
    print("=" * 80)
    by_cat = df.groupby("category")[METRIC_COLS].mean().round(3)
    cat_order = ["factual", "thematic", "relational", "comparative"]
    by_cat = by_cat.reindex([c for c in cat_order if c in by_cat.index])
    print(by_cat.to_string())

    print("\n" + "=" * 80)
    print("OVERALL MEAN")
    print("=" * 80)
    print(df[METRIC_COLS].mean().round(3).to_string())
    print("=" * 80)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    with open(DATASET_PATH, encoding="utf-8") as f:
        dataset = json.load(f)
    items = dataset["items"]
    print(f"Loaded {len(items)} eval items from {DATASET_PATH.name}\n")

    print("--- Collecting predictions from /query ---")
    records = await collect_predictions(items)

    print("\n--- Running Ragas evaluation ---")
    print("    Expect ~20-25 min on Groq free tier rate limits.")
    df = run_ragas(records)

    df["movie_recall"] = compute_movie_recall(records)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    versioned = RESULTS_DIR / f"hybrid_{timestamp}.csv"
    latest = RESULTS_DIR / "hybrid_latest.csv"
    df.to_csv(versioned, index=False)
    df.to_csv(latest, index=False)
    print(f"\nFull results: {versioned}")
    print(f"Latest alias: {latest}")

    print_summary(df)


if __name__ == "__main__":
    # Same Windows fix you applied for psycopg — harmless on other platforms.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
