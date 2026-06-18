# app/graph/router.py
"""
Query router: decides which graph query templates to fire for a given
user question, based on the entities extracted from it.

This is intentionally a rule-based router, not an LLM-based one. Reasons:
  1. It's deterministic — same input, same plan. Trivial to debug.
  2. It's fast — no extra LLM call per query.
  3. It's evaluable — you can read the rules and predict behavior.
  4. The decision surface is small enough that rules cover it.

If you ever outgrow this, the upgrade path is to replace `plan()` with
an LLM call returning structured JSON. The contract stays the same.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import psycopg

from app.graph.entities import Entity, extract_entities
from app.graph.queries import (
    GraphHit,
    movies_by_person,
    movies_by_people_intersection,
    related_movies_by_shared_entities,
    movies_by_genres_and_keywords,
    path_between_people,
    PersonPath,
)

# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------
#
# We classify the user's question into one of a few coarse intents.
# Each intent maps to a specific graph query template (or none).
#
# This is a bag-of-keywords classifier, not ML. It's good enough because:
#   - The vocabulary of "graph-shaped" questions is small.
#   - False positives degrade gracefully — we still run hybrid retrieval
#     afterward, so the worst case is "we ran an extra cheap SQL query".

Intent = Literal[
    "person_intersection",   # "movies with X and Y"
    "person_filmography",    # "what did Nolan direct"
    "similar_to_movie",      # "movies like Inception"
    "tag_filter",            # "dark sci-fi about memory"
    "connection_path",       # "how is X connected to Y"
    "none",                  # not a graph-shaped question
]

# Regex patterns are case-insensitive matches against the raw query.
# Order matters: first match wins, so put more specific patterns first.
_INTENT_PATTERNS: list[tuple[Intent, re.Pattern]] = [
    ("connection_path", re.compile(
        r"\b(connect(ed|ion)?|path|link(ed)?|between|degrees? of|how.*related)\b",
        re.IGNORECASE)),
    ("similar_to_movie", re.compile(
        r"\b(similar to|like|reminds? me of|in the (style|vein) of|comparable to)\b",
        re.IGNORECASE)),
    ("person_intersection", re.compile(
        # "with X and Y", "X and Y", "X with Y", "collaborated", "worked together"
        r"\b(with .+ and|and .+ (movie|film)|collaborat|worked (with|together)|"
        r"co-?star|both)\b",
        re.IGNORECASE)),
    ("person_filmography", re.compile(
        r"\b(direct(ed)?|star(red|ring)?|acted|played|wrote|produced|filmography)\b",
        re.IGNORECASE)),
    ("tag_filter", re.compile(
        r"\b(about|featuring|involving|themes? of|genre|category)\b",
        re.IGNORECASE)),
]


def detect_intent(query: str, entities: list[Entity]) -> Intent:
    """
    Pick an intent for this query.

    Rules layered on top of regex matches — entity counts override
    the regex when they're decisive.
    """
    people = [e for e in entities if e.type == "person"]
    movies = [e for e in entities if e.type == "movie"]
    tags = [e for e in entities if e.type in ("genre", "keyword")]
    strong_tags = [t for t in tags if t.score >= 0.72]

    # Decisive overrides based purely on entity shape.
    # Two+ people in the query → almost certainly an intersection or path.
    if len(people) >= 2:
        # Regex breaks the tie between intersection vs path.
        for intent, pat in _INTENT_PATTERNS:
            if intent == "connection_path" and pat.search(query):
                return "connection_path"
        return "person_intersection"

    # "similar to <movie>" — one movie entity + similarity language.
    if len(movies) >= 1:
        for intent, pat in _INTENT_PATTERNS:
            if intent == "similar_to_movie" and pat.search(query):
                return "similar_to_movie"

    # Regex fallthrough.
    for intent, pat in _INTENT_PATTERNS:
        if pat.search(query):
            # Sanity-check: intent requires entities of the right type.
            if intent == "person_filmography" and not people:
                continue
            if intent == "tag_filter" and not strong_tags:
                continue
            if intent == "similar_to_movie" and not movies:
                continue
            if intent in ("person_intersection", "connection_path") and len(people) < 2:
                continue
            return intent

    # If we have any structural entities at all but no clear intent,
    # default to tag_filter (which works with people too, via filmography).
    if strong_tags:
        return "tag_filter"
    if people:
        return "person_filmography"

    return "none"


# ---------------------------------------------------------------------------
# Role detection (for filmography queries)
# ---------------------------------------------------------------------------

_ROLE_PATTERNS = {
    "director": re.compile(r"\bdirect(ed|or|ing)?\b", re.IGNORECASE),
    "writer":   re.compile(r"\bwr(ote|itten|iter|iting)\b", re.IGNORECASE),
    "producer": re.compile(r"\bproduce[dr]?\b", re.IGNORECASE),
    "actor":    re.compile(r"\b(star(red|ring)?|acted|played|act(or|ress))\b",
                           re.IGNORECASE),
}


def detect_role(query: str) -> str:
    """Return one of: 'actor', 'director', 'writer', 'producer', 'any'."""
    for role, pat in _ROLE_PATTERNS.items():
        if pat.search(query):
            # Producer is not ingested into movie_people; fall back to any roles.
            if role == "producer":
                return "any"
            return role
    return "any"


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

@dataclass
class GraphPlan:
    intent: Intent
    entities: list[Entity]
    hits: list[GraphHit] = field(default_factory=list)
    path: PersonPath | None = None      # only set for connection_path
    notes: list[str] = field(default_factory=list)  # debug breadcrumbs


async def plan_and_execute(
    conn: psycopg.AsyncConnection,
    query: str,
    *,
    limit: int = 50,
) -> GraphPlan:
    """
    Top-level entry point: extract entities, pick an intent, run the
    matching graph query, return a GraphPlan with hits attached.

    Returns an empty plan (intent='none', no hits) if the question
    isn't graph-shaped — the caller should fall back to hybrid retrieval.
    """
    entities = await extract_entities(conn, query)
    intent = detect_intent(query, entities) if entities else "none"

    plan = GraphPlan(intent=intent, entities=entities)
    plan.notes.append(f"extracted {len(entities)} entities; intent={intent}")

    if intent == "none":
        return plan

    people = [e for e in entities if e.type == "person"]
    movies = [e for e in entities if e.type == "movie"]
    genres = [e for e in entities if e.type == "genre"]
    keywords = [e for e in entities if e.type == "keyword"]

    if intent == "person_intersection":
        person_ids = [e.id for e in people]
        plan.hits = await movies_by_people_intersection(conn, person_ids, limit=limit)
        plan.notes.append(f"intersection over person_ids={person_ids}")

    elif intent == "person_filmography":
        # Use the highest-scoring person entity.
        person = people[0]
        role = detect_role(query)
        plan.hits = await movies_by_person(conn, person.id, role=role, limit=limit)  # type: ignore[arg-type]
        plan.notes.append(f"filmography person={person.id} role={role}")

    elif intent == "similar_to_movie":
        movie = movies[0]
        plan.hits = await related_movies_by_shared_entities(conn, movie.id, limit=limit)
        plan.notes.append(f"similar_to movie={movie.id}")

    elif intent == "tag_filter":
        strong_keywords = [e for e in keywords if e.score >= 0.72]
        strong_genres = [e for e in genres if e.score >= 0.72]
        plan.hits = await movies_by_genres_and_keywords(
            conn,
            genre_ids=[e.id for e in strong_genres],
            keyword_ids=[e.id for e in strong_keywords],
            limit=limit,
        )
        # If there are also people in the query, narrow further by
        # intersecting with the person's filmography.
        if people:
            person_hits = await movies_by_person(conn, people[0].id, role="any", limit=200)
            allowed = {h.movie_id for h in person_hits}
            plan.hits = [h for h in plan.hits if h.movie_id in allowed]
            plan.notes.append(f"narrowed by person={people[0].id}")
        plan.notes.append(
            f"tag_filter genres={[e.id for e in strong_genres]} "
            f"keywords={[e.id for e in strong_keywords]}"
        )

    elif intent == "connection_path":
        if len(people) >= 2:
            plan.path = await path_between_people(conn, people[0].id, people[1].id)
            if plan.path:
                # Represent the path as a sequence of "hits" — the movies
                # along the path — so the retriever can fetch context for them.
                plan.hits = [
                    GraphHit(
                        movie_id=mid,
                        score=1.0 - (i * 0.1),
                        reason=f"step {i + 1} on path from "
                               f"{people[0].name} to {people[1].name}",
                    )
                    for i, mid in enumerate(plan.path.movie_path)
                ]
                plan.notes.append(
                    f"path depth={plan.path.depth} "
                    f"people={plan.path.person_path}"
                )
            else:
                plan.notes.append("no path found within max_hops")

    return plan
