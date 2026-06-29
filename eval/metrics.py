"""Deterministic retrieval metrics used by the evaluation runners."""

from collections.abc import Collection, Iterable, Sequence
import unicodedata


def normalize_title(title: str) -> str:
    """Normalize a movie title for exact, case-insensitive comparison."""
    normalized = unicodedata.normalize("NFKC", title)
    return " ".join(normalized.split()).casefold()


def reciprocal_rank_at_k(
    retrieved_titles: Sequence[str],
    relevant_titles: Collection[str],
    k: int,
) -> tuple[str | None, int | None, float]:
    """Return the first relevant title, its one-based rank, and RR@k."""
    if k <= 0:
        raise ValueError("k must be greater than zero")

    normalized_relevant = {normalize_title(title) for title in relevant_titles}
    for rank, title in enumerate(retrieved_titles[:k], start=1):
        if normalize_title(title) in normalized_relevant:
            return title, rank, 1.0 / rank

    return None, None, 0.0


def recall_at_k(
    retrieved_titles: Sequence[str],
    relevant_titles: Collection[str],
    k: int,
) -> float:
    """Return the fraction of unique relevant titles retrieved within k."""
    if k <= 0:
        raise ValueError("k must be greater than zero")

    normalized_relevant = {normalize_title(title) for title in relevant_titles}
    if not normalized_relevant:
        raise ValueError("at least one relevant title is required")

    normalized_retrieved = {
        normalize_title(title) for title in retrieved_titles[:k]
    }
    return len(normalized_relevant & normalized_retrieved) / len(normalized_relevant)


def mean_reciprocal_rank(scores: Iterable[float]) -> float:
    """Return the arithmetic mean of per-query reciprocal-rank scores."""
    values = list(scores)
    if not values:
        raise ValueError("at least one reciprocal-rank score is required")
    return sum(values) / len(values)
