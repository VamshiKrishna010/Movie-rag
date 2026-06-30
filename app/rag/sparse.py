"""Sparse (lexical) retriever using Postgres full-text search.

Pairs with the dense (pgvector) retriever for hybrid retrieval.
Uses websearch_to_tsquery for forgiving query parsing and ts_rank_cd
(cover density) for ranking.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from psycopg import AsyncConnection
from psycopg.rows import dict_row


@dataclass
class SparseHit:
    chunk_id: int
    movie_id: int
    content: str
    score: float  # ts_rank_cd score; higher is better


_QUERY_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_SPARSE_STOPWORDS = {
    "a",
    "about",
    "an",
    "and",
    "appeared",
    "appears",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "besides",
    "both",
    "by",
    "can",
    "centered",
    "compare",
    "compared",
    "did",
    "differ",
    "directed",
    "director",
    "directors",
    "do",
    "does",
    "elements",
    "feature",
    "featuring",
    "film",
    "films",
    "focused",
    "for",
    "from",
    "had",
    "has",
    "have",
    "having",
    "how",
    "in",
    "into",
    "is",
    "it",
    "its",
    "list",
    "made",
    "major",
    "make",
    "movie",
    "movies",
    "of",
    "on",
    "original",
    "other",
    "played",
    "plays",
    "portray",
    "portrayal",
    "released",
    "share",
    "shared",
    "star",
    "starred",
    "starring",
    "stars",
    "style",
    "stylistic",
    "that",
    "the",
    "their",
    "them",
    "thematically",
    "these",
    "this",
    "those",
    "through",
    "treatment",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
    "year",
    "years",
}


def build_loose_tsquery(query: str) -> str:
    """Build an OR-prefix tsquery from meaningful user terms.

    Postgres websearch queries are high precision, but they are too strict for
    multi-entity prompts. This loose query gives sparse retrieval a recall path
    while keeping generic prompt words out of the index scan.
    """
    terms: list[str] = []
    seen = set()
    for token in _QUERY_TOKEN_RE.findall(query.casefold()):
        if len(token) < 2 or token in _SPARSE_STOPWORDS or token in seen:
            continue
        seen.add(token)
        terms.append(f"{token}:*")
    return " | ".join(terms)


async def sparse_retrieve(
    conn: AsyncConnection,
    query: str,
    k: int = 20,
) -> list[SparseHit]:
    """Return top-k chunks by lexical match against the query.

    Uses websearch_to_tsquery so user input like 'sci-fi "space opera" -horror'
    parses sensibly without raising. Returns [] if the query has no
    indexable terms (e.g. all stopwords).
    """
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
        scored AS (
          SELECT
            c.id AS chunk_id,
            c.movie_id,
            c.content,
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
            ) AS score
          FROM candidate_chunks cc
          JOIN chunks c ON c.id = cc.chunk_id
          CROSS JOIN query_terms qt
          LEFT JOIN metadata_movies mm ON mm.movie_id = c.movie_id
        )
        SELECT
            chunk_id,
            movie_id,
            content,
            score
        FROM scored
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
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            sql,
            {
                "question": query,
                "loose_tsquery": build_loose_tsquery(query),
                "fts_pool": max(k * 80, 200),
                "k": k,
            },
        )
        rows = await cur.fetchall()

    return [
        SparseHit(
            chunk_id=r["chunk_id"],
            movie_id=r["movie_id"],
            content=r["content"],
            score=float(r["score"]),
        )
        for r in rows
    ]
