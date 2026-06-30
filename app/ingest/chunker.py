from dataclasses import dataclass
import re

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True)
class ChunkRecord:
    movie_id: int
    chunk_type: str
    content: str


CHUNK_TYPES = ("full", "plot", "themes")

_THEME_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "dreams and reality",
        (
            "dream",
            "dreams",
            "nightmare",
            "subconscious",
            "sleep",
            "surreal",
            "reality",
            "illusion",
            "hallucination",
        ),
    ),
    (
        "isolation and survival",
        (
            "survival",
            "survive",
            "stranded",
            "isolated",
            "isolation",
            "alone",
            "wilderness",
            "castaway",
            "trapped",
            "desert island",
            "lost at sea",
        ),
    ),
    (
        "space and alien worlds",
        (
            "space",
            "astronaut",
            "mars",
            "nasa",
            "spaceship",
            "spacecraft",
            "orbit",
            "planet",
            "galaxy",
            "alien",
            "aliens",
            "extraterrestrial",
            "first contact",
        ),
    ),
    (
        "class inequality",
        (
            "class",
            "poverty",
            "poor",
            "rich",
            "wealth",
            "wealthy",
            "capitalism",
            "inequality",
            "economic",
            "worker",
            "working class",
            "anti-capitalist",
            "social commentary",
            "corporate",
        ),
    ),
    (
        "memory and identity",
        (
            "memory",
            "memories",
            "amnesia",
            "identity",
            "remember",
            "forgotten",
            "past",
            "mind",
        ),
    ),
    (
        "artificial intelligence and robots",
        (
            "artificial intelligence",
            "a.i.",
            "robot",
            "robots",
            "android",
            "cyborg",
            "machine",
            "replicant",
            "consciousness",
            "humanoid robot",
            "human android relationship",
        ),
    ),
    (
        "heist plan",
        (
            "heist",
            "robbery",
            "robber",
            "thief",
            "thieves",
            "steal",
            "casino",
            "bank",
            "banks",
            "con artist",
            "caper",
            "master plan",
            "gold heist",
        ),
    ),
    (
        "fractured storytelling",
        (
            "nonlinear",
            "non-linear",
            "chronological",
            "flashback",
            "time loop",
            "fragmented",
            "fractured",
        ),
    ),
    (
        "artificial reality and control",
        (
            "simulation",
            "virtual reality",
            "matrix",
            "controlled",
            "experiment",
            "surveillance",
            "manufactured",
            "alternate reality",
            "simulated reality",
            "artificial reality",
            "controlled reality",
            "reality is controlled",
            "make believe",
            "hidden camera",
        ),
    ),
    (
        "doubles and divided identity",
        (
            "alter ego",
            "dissociative identity disorder",
            "doppelgänger",
            "doppelganger",
            "double identity",
            "double life",
            "dual identity",
            "look-alike",
            "lookalike",
            "split personality",
            "twin",
            "twins",
        ),
    ),
    (
        "found family",
        (
            "found family",
            "strangers",
            "misfit",
            "misfits",
            "team",
            "family",
            "foster family",
            "dysfunctional family",
            "friendship",
            "bond",
            "community",
            "guardians",
        ),
    ),
    (
        "coming of age and belonging",
        (
            "coming of age",
            "teenager",
            "adolescence",
            "growing up",
            "youth",
            "belonging",
            "school",
            "childhood",
            "teenage",
            "teen",
            "self-discovery",
        ),
    ),
    (
        "immigrant identity and two cultures",
        (
            "immigrant",
            "immigration",
            "asian american",
            "chinese american",
            "culture clash",
            "two cultures",
            "generations conflict",
            "family reunion",
        ),
    ),
    (
        "grief and loss",
        (
            "grief",
            "grieving",
            "loss",
            "death",
            "mourning",
            "trauma",
            "haunted",
            "ghost",
            "loss of loved one",
        ),
    ),
    (
        "revenge and obsession",
        (
            "revenge",
            "vengeance",
            "avenge",
            "vendetta",
            "retribution",
            "payback",
            "obsession",
        ),
    ),
    (
        "media manipulation",
        (
            "media",
            "television",
            "news",
            "journalist",
            "camera",
            "broadcast",
            "reality show",
            "narrative",
            "celebrity",
            "manufactured",
            "propaganda",
            "reality tv",
            "tv show",
        ),
    ),
    (
        "authoritarian resistance",
        (
            "authoritarian",
            "dictatorship",
            "totalitarian",
            "regime",
            "resistance",
            "rebellion",
            "rebel",
            "oppression",
            "revolution",
            "fascism",
            "fascist",
            "orwellian",
            "government",
        ),
    ),
    (
        "moral ambiguity",
        (
            "antihero",
            "anti-hero",
            "villain",
            "hero",
            "moral",
            "corruption",
            "outlaw",
            "justice",
            "crime",
            "right and justice",
            "regret",
            "sheriff",
            "bounty hunter",
        ),
    ),
    (
        "psychological thriller",
        (
            "psychological",
            "thriller",
            "paranoia",
            "delusion",
            "mental",
            "unreliable",
            "mystery",
            "mind game",
            "insomnia",
        ),
    ),
    (
        "environmental collapse",
        (
            "environmental",
            "climate",
            "collapse",
            "disaster",
            "post-apocalyptic",
            "apocalypse",
            "global warming",
            "ice age",
            "flood",
            "famine",
            "garbage",
            "pollution",
            "cataclysmic storm",
            "climate change",
            "end of the world",
        ),
    ),
    (
        "finance greed and corruption",
        (
            "finance",
            "wall street",
            "stock",
            "banker",
            "money",
            "greed",
            "fraud",
            "capitalism",
        ),
    ),
    (
        "war trauma",
        (
            "war",
            "soldier",
            "combat",
            "military",
            "ptsd",
            "battle",
            "vietnam",
            "trauma",
        ),
    ),
    (
        "music and artistic ambition",
        (
            "music",
            "musician",
            "band",
            "drummer",
            "jazz",
            "singer",
            "artist",
            "performance",
            "ambition",
            "sacrifice",
            "craft",
        ),
    ),
    (
        "road trip friendship",
        (
            "road trip",
            "road movie",
            "roadtrip",
            "driver",
            "buddy",
            "unlikely friendship",
            "journey",
        ),
    ),
    (
        "cooking and creativity",
        (
            "cook",
            "chef",
            "restaurant",
            "food",
            "cuisine",
            "cooking",
            "kitchen",
            "creativity",
        ),
    ),
    (
        "multiverse and parallel worlds",
        (
            "multiverse",
            "parallel universe",
            "alternate universe",
            "multiple universe",
            "portal",
            "dimension",
        ),
    ),
    (
        "courtroom justice",
        (
            "courtroom",
            "trial",
            "lawyer",
            "jury",
            "judge",
            "legal",
            "doubt",
            "justice",
        ),
    ),
    (
        "loneliness and alienation",
        (
            "loneliness",
            "lonely",
            "alienation",
            "city",
            "urban",
            "isolated",
        ),
    ),
)

_THEME_ALIASES: dict[str, tuple[str, ...]] = {
    "dreams and reality": (
        "dreams within dreams",
        "nested dreams",
        "dream world",
        "dreams blur reality",
        "boundary between dreams and reality",
    ),
    "isolation and survival": (
        "survival against isolation",
        "stranded alone",
        "survival under extreme conditions",
        "isolated survivor",
    ),
    "space and alien worlds": (
        "space survival",
        "human isolation in space",
        "space exploration",
        "first contact with aliens",
    ),
    "class inequality": (
        "class struggle",
        "economic inequality",
        "rich and poor",
        "social hierarchy",
        "wealth inequality",
    ),
    "memory and identity": (
        "memory loss",
        "fractured identity",
        "identity crisis",
        "lost memory",
    ),
    "artificial intelligence and robots": (
        "artificial intelligence developing consciousness",
        "robots learning empathy",
        "robots learning humanity",
        "machine consciousness",
        "human android relationship",
    ),
    "heist plan": (
        "elaborate heist",
        "multi-step plan",
        "ensemble heist",
        "lighthearted heist",
        "master plan",
    ),
    "fractured storytelling": (
        "nonlinear chronology",
        "non-linear order",
        "fragmented narrative",
        "chronological puzzle",
    ),
    "artificial reality and control": (
        "artificial reality",
        "controlled reality",
        "simulated reality",
        "manufactured world",
        "reality is controlled",
    ),
    "doubles and divided identity": (
        "divided identity",
        "psychological doubles",
        "double life",
        "split personality",
        "look alike identity",
    ),
    "found family": (
        "strangers becoming found family",
        "unlikely found family",
        "misfits become a team",
        "chosen family",
        "group bonding",
    ),
    "coming of age and belonging": (
        "coming-of-age",
        "identity and belonging",
        "growing up",
        "finding belonging",
    ),
    "immigrant identity and two cultures": (
        "immigrant families balancing two cultures",
        "two cultures",
        "immigrant family identity",
        "intergenerational immigrant family",
    ),
    "grief and loss": (
        "grief and trauma",
        "mourning and loss",
        "supernatural grief",
        "grief takes a supernatural form",
    ),
    "revenge and obsession": (
        "vengeance consumes the protagonist",
        "revenge obsession",
        "revenge quest",
        "cycle of vengeance",
    ),
    "media manipulation": (
        "media manipulation",
        "manufactured narratives",
        "public narrative control",
        "reality television manipulation",
    ),
    "authoritarian resistance": (
        "ordinary people resisting authoritarian systems",
        "resisting fascism",
        "fighting oppressive government",
        "anti-authoritarian rebellion",
    ),
    "moral ambiguity": (
        "moral ambiguity",
        "heroes and villains are not simple",
        "questioning heroes and villains",
        "antihero morality",
    ),
    "psychological thriller": (
        "unreliable narrator",
        "fractured perception",
        "psychological mind game",
        "paranoia and delusion",
    ),
    "environmental collapse": (
        "environmental collapse",
        "surviving environmental collapse",
        "climate disaster",
        "post-apocalyptic survival",
    ),
    "finance greed and corruption": (
        "greed and corruption in high finance",
        "financial corruption",
        "Wall Street greed",
        "money and fraud",
    ),
    "war trauma": (
        "lasting psychological trauma",
        "soldiers psychological trauma",
        "war trauma",
        "combat trauma",
    ),
    "music and artistic ambition": (
        "musicians sacrificing stability for their craft",
        "artistic ambition",
        "creative obsession",
        "music and sacrifice",
    ),
    "cooking and creativity": (
        "cooking as creativity",
        "food as identity",
        "culinary creativity",
        "restaurant creativity",
    ),
    "road trip friendship": (
        "road movies where unlikely friendship develops",
        "unlikely friendship on a road trip",
        "road trip bonding",
        "buddy road movie",
    ),
    "multiverse and parallel worlds": (
        "multiple universes",
        "parallel worlds",
        "alternate universes",
        "travel through multiple universes",
    ),
    "courtroom justice": (
        "courtroom doubt",
        "meaning of justice",
        "legal drama about doubt",
        "jury and justice",
    ),
    "loneliness and alienation": (
        "loneliness in a crowded city",
        "urban loneliness",
        "alienation in the city",
        "isolated in a crowd",
    ),
}


CHUNK_QUERY = """
SELECT
    m.id,
    m.title,
    m.release_year,
    m.overview,
    m.tagline,
    -- Directors
    (
        SELECT array_agg(p.name ORDER BY p.name)
        FROM movie_people mp
        JOIN people p ON p.id = mp.person_id
        WHERE mp.movie_id = m.id AND mp.role = 'director'
    ) AS directors,
    -- Writers
    (
        SELECT array_agg(p.name ORDER BY p.name)
        FROM movie_people mp
        JOIN people p ON p.id = mp.person_id
        WHERE mp.movie_id = m.id AND mp.role = 'writer'
    ) AS writers,
    -- Top cast (ordered by billing)
    (
        SELECT array_agg(p.name ORDER BY mp.cast_order NULLS LAST)
        FROM movie_people mp
        JOIN people p ON p.id = mp.person_id
        WHERE mp.movie_id = m.id AND mp.role = 'actor'
    ) AS cast_list,
    -- Genres
    (
        SELECT array_agg(g.name ORDER BY g.name)
        FROM movie_genres mg
        JOIN genres g ON g.id = mg.genre_id
        WHERE mg.movie_id = m.id
    ) AS genres,
    -- Keywords
    (
        SELECT array_agg(k.name ORDER BY k.name)
        FROM movie_keywords mk
        JOIN keywords k ON k.id = mk.keyword_id
        WHERE mk.movie_id = m.id
    ) AS keywords,
    ARRAY[]::text[] AS existing_chunk_types
FROM movies m
ORDER BY m.id;
"""

CHUNK_QUERY_MISSING = """
SELECT
    m.id,
    m.title,
    m.release_year,
    m.overview,
    m.tagline,
    (
        SELECT array_agg(p.name ORDER BY p.name)
        FROM movie_people mp
        JOIN people p ON p.id = mp.person_id
        WHERE mp.movie_id = m.id AND mp.role = 'director'
    ) AS directors,
    (
        SELECT array_agg(p.name ORDER BY p.name)
        FROM movie_people mp
        JOIN people p ON p.id = mp.person_id
        WHERE mp.movie_id = m.id AND mp.role = 'writer'
    ) AS writers,
    (
        SELECT array_agg(p.name ORDER BY mp.cast_order NULLS LAST)
        FROM movie_people mp
        JOIN people p ON p.id = mp.person_id
        WHERE mp.movie_id = m.id AND mp.role = 'actor'
    ) AS cast_list,
    (
        SELECT array_agg(g.name ORDER BY g.name)
        FROM movie_genres mg
        JOIN genres g ON g.id = mg.genre_id
        WHERE mg.movie_id = m.id
    ) AS genres,
    (
        SELECT array_agg(k.name ORDER BY k.name)
        FROM movie_keywords mk
        JOIN keywords k ON k.id = mk.keyword_id
        WHERE mk.movie_id = m.id
    ) AS keywords,
    (
        SELECT array_agg(c.chunk_type)
        FROM chunks c
        WHERE c.movie_id = m.id AND c.chunk_type = ANY(%(chunk_types)s)
    ) AS existing_chunk_types
FROM movies m
WHERE NOT EXISTS (
    SELECT 1 FROM chunks c
    WHERE c.movie_id = m.id AND c.chunk_type = 'full'
)
OR NOT EXISTS (
    SELECT 1 FROM chunks c
    WHERE c.movie_id = m.id AND c.chunk_type = 'plot'
)
OR NOT EXISTS (
    SELECT 1 FROM chunks c
    WHERE c.movie_id = m.id AND c.chunk_type = 'themes'
)
ORDER BY m.id;
"""


def _join(items: list[str] | None, limit: int | None = None) -> str:
    """Comma-separate a list, optionally capping length."""
    if not items:
        return ""
    if limit:
        items = items[:limit]
    return ", ".join(items)


def _search_index(row: dict) -> tuple[str, set[str]]:
    values = [
        row.get("title"),
        row.get("tagline"),
        row.get("overview"),
        _join(row.get("genres")),
        _join(row.get("keywords")),
    ]
    text = " ".join(value for value in values if value).lower()
    return text, set(re.findall(r"[a-z0-9]+", text))


def _matched_labels(
    text: str,
    tokens: set[str],
    rules: tuple[tuple[str, tuple[str, ...]], ...],
) -> list[str]:
    return [
        label
        for label, terms in rules
        if any(_contains_term(text, tokens, term) for term in terms)
    ]


def _contains_term(text: str, tokens: set[str], term: str) -> bool:
    if term.isascii() and term.isalnum():
        return term in tokens
    return term in text


def _theme_aliases(labels: list[str]) -> list[str]:
    aliases = []
    seen = set()
    for label in labels:
        for alias in _THEME_ALIASES.get(label, ()):
            if alias in seen:
                continue
            seen.add(alias)
            aliases.append(alias)
    return aliases


def _excerpt(text: str | None, limit: int = 360) -> str:
    if not text:
        return ""
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "."


def _format_full_chunk(row: dict) -> str:
    """Build the rich text chunk for one movie."""
    parts = []

    # Title + year
    year_str = f" ({row['release_year']})" if row["release_year"] else ""
    parts.append(f"{row['title']}{year_str}.")

    # Directors
    directors = _join(row["directors"])
    if directors:
        parts.append(f"Directed by {directors}.")

    # Writers (limit 3 — long writer lists are noise)
    writers = _join(row["writers"], limit=3)
    if writers:
        parts.append(f"Written by {writers}.")

    # Cast (top 5 by billing order)
    cast = _join(row["cast_list"], limit=5)
    if cast:
        parts.append(f"Starring {cast}.")

    # Genres
    genres = _join(row["genres"])
    if genres:
        parts.append(f"Genres: {genres}.")

    # Tagline
    if row["tagline"]:
        parts.append(f"Tagline: {row['tagline']}")

    # Overview (the meat)
    if row["overview"]:
        parts.append(f"Plot summary: {row['overview']}")

    # Keywords
    keywords = _join(row["keywords"])
    if keywords:
        parts.append(f"Keywords: {keywords}.")

    return " ".join(parts)


def _format_plot_chunk(row: dict) -> str:
    """Build a plot-heavy chunk for thematic retrieval."""
    parts = []

    year_str = f" ({row['release_year']})" if row["release_year"] else ""
    parts.append(f"Movie: {row['title']}{year_str}.")

    genres = _join(row["genres"])
    if genres:
        parts.append(f"Genres: {genres}.")

    if row["tagline"]:
        parts.append(f"Tagline: {row['tagline']}")

    if row["overview"]:
        parts.append(f"Plot summary: {row['overview']}")

    keywords = _join(row["keywords"])
    if keywords:
        parts.append(f"Themes and story keywords: {keywords}.")

    return " ".join(parts)


def _format_themes_chunk(row: dict) -> str:
    """Build a heuristic theme chunk from local TMDB metadata."""
    parts = []

    year_str = f" ({row['release_year']})" if row["release_year"] else ""
    parts.append(f"Movie: {row['title']}{year_str}.")

    genres = _join(row["genres"])
    if genres:
        parts.append(f"Genres: {genres}.")

    search_text, search_tokens = _search_index(row)
    themes = _matched_labels(search_text, search_tokens, _THEME_RULES)
    if themes:
        parts.append(f"Themes: {_join(themes)}.")
        aliases = _theme_aliases(themes)
        if aliases:
            parts.append(f"Theme search phrases: {_join(aliases)}.")

    keywords = _join(row["keywords"])
    if keywords:
        parts.append(f"TMDB keywords: {keywords}.")

    if row["tagline"]:
        parts.append(f"Tagline clue: {row['tagline']}")

    overview = _excerpt(row.get("overview"))
    if overview:
        parts.append(f"Plot clues: {overview}")

    return " ".join(parts)


def _chunk_records_for_row(row: dict) -> list[ChunkRecord]:
    existing = set(row.get("existing_chunk_types") or [])
    candidates = {
        "full": _format_full_chunk(row),
        "plot": _format_plot_chunk(row),
        "themes": _format_themes_chunk(row),
    }
    return [
        ChunkRecord(row["id"], chunk_type, content)
        for chunk_type, content in candidates.items()
        if chunk_type not in existing and content.strip()
    ]


async def build_chunks(conn: psycopg.AsyncConnection) -> list[ChunkRecord]:
    """Returns all chunk records for every movie in the DB."""
    return await _run_chunk_query(conn, CHUNK_QUERY)


async def build_chunks_missing(conn: psycopg.AsyncConnection) -> list[ChunkRecord]:
    """Returns chunk records for movies missing one or more expected chunk types."""
    return await _run_chunk_query(
        conn,
        CHUNK_QUERY_MISSING,
        {"chunk_types": list(CHUNK_TYPES)},
    )


async def _run_chunk_query(
    conn: psycopg.AsyncConnection,
    sql: str,
    params: dict | None = None,
) -> list[ChunkRecord]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()
    return [
        chunk
        for row in rows
        for chunk in _chunk_records_for_row(row)
    ]
