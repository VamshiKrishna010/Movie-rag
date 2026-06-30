"""Deterministic query routing for retrieval strategy selection."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal


QueryCategory = Literal[
    "comparative",
    "factual",
    "indirect",
    "relational",
    "thematic",
    "unknown",
]
RetrievalStrategy = Literal["dense", "hybrid", "sparse"]


@dataclass(frozen=True)
class QueryRoute:
    category: QueryCategory
    strategy: RetrievalStrategy


_COMPARATIVE_PATTERNS = (
    re.compile(r"\bcompare\b"),
    re.compile(r"\bversus\b|\bvs\.?\b"),
    re.compile(r"\bdiffer(?:s|ent|ence|ences)?\b"),
    re.compile(r"\bsimilarit(?:y|ies)\b"),
    re.compile(r"\bwhat do\b.+\bshare\b"),
    re.compile(r"\bhow (?:do|does|is|are)\b.+\bconnected\b"),
)

_FACTUAL_PATTERNS = (
    re.compile(r"^who (?:directed|played|plays|wrote)\b"),
    re.compile(r"^what year\b"),
    re.compile(r"\breleased\?$"),
)

_RELATIONAL_PATTERNS = (
    re.compile(r"\bboth\b"),
    re.compile(r"\bpair(?:s|ed)?\b"),
    re.compile(r"\bworked with\b"),
    re.compile(r"\bmade with\b"),
    re.compile(r"\bdirector of\b"),
    re.compile(r"\bother films?\b"),
    re.compile(r"\bbesides\b"),
    re.compile(r"\bwith director\b"),
    re.compile(r"\bfilms? by\b.+\bbesides\b"),
)

_INDIRECT_PATTERNS = (
    re.compile(r"\bfilms?\b.+\bdirected by\b"),
    re.compile(r"\bmovies?\b.+\bdirected by\b"),
    re.compile(r"\bdirected\b.+\bfilms?\b"),
    re.compile(r"\bstarr(?:ed|ing)\b"),
    re.compile(r"\bappeared in\b"),
    re.compile(r"\bscored by\b"),
    re.compile(r"\bwritten by\b"),
    re.compile(r"\bcinematography by\b"),
    re.compile(r"\bwhat films? did\b"),
    re.compile(r"\bwhich movies? has\b"),
    re.compile(r"\blist the films?\b"),
)

_THEMATIC_PATTERNS = (
    re.compile(r"\bmovies? about\b"),
    re.compile(r"\bfilms? about\b"),
    re.compile(r"\bcentered on\b"),
    re.compile(r"\bfocused on\b"),
    re.compile(r"\bportraying\b"),
    re.compile(r"\bportray\b"),
    re.compile(r"\bexplore\b"),
    re.compile(r"\bthemes?\b"),
    re.compile(r"\bthrillers? with\b"),
    re.compile(r"\bhorror films? where\b"),
    re.compile(r"\bwesterns? that\b"),
    re.compile(r"\bscience[- ]fiction films? about\b"),
    re.compile(r"\bwhere .+\b(?:becomes|creates|develops|travels|surviving)\b"),
)


def classify_query(question: str) -> QueryCategory:
    text = " ".join(question.casefold().split())

    if any(pattern.search(text) for pattern in _COMPARATIVE_PATTERNS):
        return "comparative"
    if any(pattern.search(text) for pattern in _FACTUAL_PATTERNS):
        return "factual"
    if any(pattern.search(text) for pattern in _RELATIONAL_PATTERNS):
        return "relational"
    if any(pattern.search(text) for pattern in _INDIRECT_PATTERNS):
        return "indirect"
    if any(pattern.search(text) for pattern in _THEMATIC_PATTERNS):
        return "thematic"
    return "unknown"


def route_query(question: str) -> QueryRoute:
    category = classify_query(question)
    strategy_by_category: dict[QueryCategory, RetrievalStrategy] = {
        "comparative": "sparse",
        "factual": "sparse",
        "indirect": "sparse",
        "relational": "sparse",
        "thematic": "dense",
        "unknown": "hybrid",
    }
    return QueryRoute(
        category=category,
        strategy=strategy_by_category[category],
    )
