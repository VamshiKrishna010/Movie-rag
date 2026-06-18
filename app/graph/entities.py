"""
Entity extraction for graph retrieval.

Given a natural-language query like:
    "What movies has Nolan directed with Christian Bale?"
we want to extract structured references to entities in our DB:
    [Person(id=525, name="Christopher Nolan"),
     Person(id=3894, name="Christian Bale")]

These IDs are what the graph query templates need as input.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Literal

import psycopg
from psycopg.rows import dict_row

from app.db import get_connection

EntityType = Literal["person", "movie", "genre", "keyword"]


@dataclass
class Entity:
    id: int
    name: str
    type: EntityType
    score: float          # match confidence 0..1
    matched_span: str     # the substring of the query that matched


_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "with", "by",
    "and", "or", "but", "is", "are", "was", "were", "be", "been", "being",
    "what", "which", "who", "whom", "whose", "when", "where", "why", "how",
    "movies", "movie", "film", "films", "directed", "starring", "stars",
    "acted", "played", "about", "between", "show", "find", "list", "tell",
    "me", "us", "i", "you", "he", "she", "it", "they", "do", "does", "did",
    "has", "have", "had", "that", "this", "these", "those", "all", "any",
    "direct", "directed", "director", "star", "stars", "starred", "starring",
    "write", "wrote", "written", "writer", "produce", "produced", "producer",
    "did", "makes", "make", "story", "audiences", "audience", "compelling",
    "emotionally", "emotional",
}


def _person_span_ok(span: str) -> bool:
    words = span.split()
    return bool(words) and all(w not in _STOPWORDS for w in words)


def _candidate_spans(query: str, max_words: int = 4) -> list[str]:
    cleaned = re.sub(r"[^\w\s']", " ", query.lower())
    words = [w for w in cleaned.split() if w]

    spans: list[str] = []
    for n in range(1, max_words + 1):
        for i in range(len(words) - n + 1):
            window = words[i : i + n]
            if all(w in _STOPWORDS for w in window):
                continue
            spans.append(" ".join(window))
    return spans


_BATCH_PERSON_SQL = """
WITH spans AS (
    SELECT span FROM unnest(%(spans)s::text[]) AS span
)
SELECT
    s.span,
    match.id,
    match.name,
    match.score
FROM spans s
CROSS JOIN LATERAL (
    SELECT
        p.id,
        p.name,
        GREATEST(
            similarity(p.name, s.span),
            word_similarity(s.span, p.name)
        ) AS score
    FROM people p
    WHERE p.name %% s.span
    ORDER BY
        score DESC,
        (SELECT COUNT(*)::int FROM movie_people mp WHERE mp.person_id = p.id) DESC,
        p.name
    LIMIT 1
) match
WHERE match.score >= %(min_score)s
"""

_BATCH_MOVIE_SQL = """
WITH spans AS (
    SELECT span FROM unnest(%(spans)s::text[]) AS span
)
SELECT
    s.span,
    match.id,
    match.name,
    match.score
FROM spans s
CROSS JOIN LATERAL (
    SELECT id, title AS name, similarity(title, s.span) AS score
    FROM movies
    WHERE title %% s.span
    ORDER BY score DESC, vote_average DESC NULLS LAST
    LIMIT 1
) match
WHERE match.score >= %(min_score)s
"""

_BATCH_GENRE_SQL = """
WITH spans AS (
    SELECT span FROM unnest(%(spans)s::text[]) AS span
)
SELECT
    s.span,
    match.id,
    match.name,
    match.score
FROM spans s
CROSS JOIN LATERAL (
    SELECT id, name, similarity(name, s.span) AS score
    FROM genres
    WHERE name ILIKE s.span OR name %% s.span
    ORDER BY score DESC
    LIMIT 1
) match
WHERE match.score >= %(min_score)s
"""

_BATCH_KEYWORD_SQL = """
WITH spans AS (
    SELECT span FROM unnest(%(spans)s::text[]) AS span
)
SELECT
    s.span,
    match.id,
    match.name,
    match.score
FROM spans s
CROSS JOIN LATERAL (
    SELECT id, name, similarity(name, s.span) AS score
    FROM keywords
    WHERE name %% s.span
    ORDER BY score DESC
    LIMIT 1
) match
WHERE match.score >= %(min_score)s
"""


async def _batch_match(
    spans: list[str],
    sql: str,
    entity_type: EntityType,
    min_score: float,
) -> list[Entity]:
    if not spans:
        return []
    async with get_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, {"spans": spans, "min_score": min_score})
            rows = await cur.fetchall()
    return [
        Entity(
            id=r["id"],
            name=r["name"],
            type=entity_type,
            score=float(r["score"]),
            matched_span=r["span"],
        )
        for r in rows
    ]


async def extract_entities(
    conn: psycopg.AsyncConnection,
    query: str,
    *,
    person_threshold: float = 0.45,
    movie_threshold: float = 0.50,
    genre_threshold: float = 0.70,
    keyword_threshold: float = 0.72,
    max_per_type: int = 5,
) -> list[Entity]:
    spans = list(dict.fromkeys(_candidate_spans(query)))
    if not spans:
        return []

    person_spans = [s for s in spans if _person_span_ok(s)]

    # Four batch queries in parallel (one per entity table) instead of 4×N.
    person_hits, movie_hits, genre_hits, keyword_hits = await asyncio.gather(
        _batch_match(person_spans, _BATCH_PERSON_SQL, "person", person_threshold),
        _batch_match(spans, _BATCH_MOVIE_SQL, "movie", movie_threshold),
        _batch_match(spans, _BATCH_GENRE_SQL, "genre", genre_threshold),
        _batch_match(spans, _BATCH_KEYWORD_SQL, "keyword", keyword_threshold),
    )
    hits = person_hits + movie_hits + genre_hits + keyword_hits

    if not hits:
        return []

    best_by_id: dict[tuple[EntityType, int], Entity] = {}
    for h in hits:
        key = (h.type, h.id)
        if key not in best_by_id or h.score > best_by_id[key].score:
            best_by_id[key] = h
    deduped = list(best_by_id.values())

    deduped.sort(key=lambda e: (-len(e.matched_span), -e.score))
    kept: list[Entity] = []
    claimed_words: set[str] = set()
    for e in deduped:
        words = set(e.matched_span.split())
        if words.issubset(claimed_words):
            continue
        kept.append(e)
        claimed_words |= words

    by_type: dict[EntityType, list[Entity]] = {}
    for e in sorted(kept, key=lambda x: -x.score):
        by_type.setdefault(e.type, []).append(e)
    final: list[Entity] = []
    for ents in by_type.values():
        final.extend(ents[:max_per_type])

    final.sort(key=lambda e: -e.score)
    return final
