# Movie RAG

A movie recommendation and Q&A backend built with **FastAPI**, **PostgreSQL + pgvector**, and **hybrid retrieval** (dense vectors, full-text search, and graph traversal over TMDB-shaped relational data).

---

## Stack

| Layer | Technology |
|--------|------------|
| API | FastAPI (`app/main.py`) |
| DB | PostgreSQL 16 with `pgvector`, `pg_trgm`, FTS (`docker-compose.yml` → `pgvector/pgvector:pg16`) |
| Embeddings | `BAAI/bge-small-en-v1.5` (384-dim, via `sentence-transformers`) |
| LLM | Cerebras API (OpenAI-compatible client in `app/rag/generator.py`) |
| External data | TMDB REST API |
| Config | Pydantic Settings from `.env` (`database_url`, `tmdb_api_key`, `cerebras_api_key`, etc.) |

---

## Quick Start

### 1. Database

```bash
docker compose up -d
```

Schema is auto-loaded from `sql/01_schema.sql`. Run migrations after ingestion:

```bash
psql $DATABASE_URL -f migrations/004_fts.sql
psql $DATABASE_URL -f migrations/005_graph_indexes.sql
psql $DATABASE_URL -f migrations/006_pg_trgm.sql
psql $DATABASE_URL -f migrations/008_users.sql
psql $DATABASE_URL -f migrations/009_auth_hardening.sql
```

### 2. Environment

Create a `.env` file in the project root:

```env
DATABASE_URL=postgresql://rag:rag@localhost:5432/movierag
TMDB_API_KEY=your_tmdb_key
CEREBRAS_API_KEY=your_cerebras_key
CEREBRAS_MODEL=gpt-oss-120b
GROQ_API_KEY=your_groq_key   # eval judge only
JWT_SECRET_KEY=your-long-random-secret
JWT_ACCESS_EXPIRE_MINUTES=15
JWT_REFRESH_EXPIRE_DAYS=30
```

### 3. Ingest & embed

```bash
python scripts/run_ingest.py    # fetch ~1000 movies from TMDB → Postgres
python scripts/run_embed.py     # chunk + embed → chunks table
```

### 4. Run the API

```bash
uvicorn app.main:app --reload --app-dir .
```

API docs: http://localhost:8000/docs

---

## Architecture

```mermaid
flowchart TB
    subgraph ingest [Ingestion Pipeline]
        TMDB[TMDB API] --> Pipeline[ingest/pipeline.py]
        Pipeline --> PG[(Postgres)]
        Chunker[ingest/chunker.py] --> Embedder[ingest/embedder.py]
        Embedder --> Store[ingest/store.py]
        Store --> PG
    end

    subgraph api [FastAPI]
        Query["POST /query"] --> RAG[rag/retriever + generator]
        Movies["GET /movies/*"] --> SQL[Direct SQL + hybrid search]
        Health["GET /health"] --> PG
    end

    subgraph retrieval [Retrieval Layers]
        RAG --> HybridSQL[Vector + FTS in one SQL]
        Movies --> HybridSQL
        GraphLayer[graph/ + retrieve/] -.->|"built, not wired to /query yet"| HybridSQL
    end

    PG --> RAG
    PG --> SQL
    PG --> GraphLayer
```

---

## Data Model

Defined in `sql/01_schema.sql` with follow-up migrations in `migrations/`.

**Relational graph (TMDB-shaped):**

- `movies` — title, year, overview, tagline, runtime, ratings, full `raw` JSONB
- `people` + `movie_people` — actors (top 10), directors, writers; `cast_order` for billing
- `genres` + `movie_genres`
- `keywords` + `movie_keywords`

**RAG layer:**

- `chunks` — one rich text chunk per movie (`chunk_type = 'full'`), `embedding vector(384)`, and FTS columns (`tsv` / `search_vector`)

Indexes support trigram fuzzy matching (`pg_trgm`), graph traversals, vector similarity, and GIN full-text search.

---

## Ingestion Pipeline

Three offline steps (`scripts/`):

1. **`ingest/pipeline.py`** — Discovers popular movies from TMDB, fetches full details (credits + keywords), caches raw JSON under `data/raw/`, upserts into Postgres.
2. **`ingest/chunker.py`** — Builds a single prose chunk per movie from title, cast, crew, genres, overview, keywords.
3. **`ingest/store.py`** — Embeds all chunks with BGE and writes vectors to `chunks`.

TMDB client (`ingest/tmdb_client.py`) uses retries, concurrency limits, and `append_to_response=credits,keywords`.

---

## API Endpoints

### Core RAG — `POST /query` (`app/api/query.py`)

Flow:

1. **Retrieve** top-k chunks via `app.rag.retriever.retrieve`
2. **Generate** answer via `app.rag.generator.generate` (Cerebras, grounded on retrieved context only)

Request body: `question`, `k` (1–20), optional `include_chunks`.

### Movie catalog — `app/api/movies.py`

| Endpoint | Purpose |
|----------|---------|
| `GET /movies/browse` | Paginated browse, sorted by `vote_average`, optional `genre_id` filter |
| `GET /movies/search` | Title ILIKE search or **hybrid semantic search** (mode: `auto` / `title` / `hybrid`) |
| `GET /movies/{id}` | Full detail: cast, crew, genres, keywords, TMDB image URLs |
| `GET /genres` | Genre list with movie counts |
| `GET /health` | Liveness + Postgres connectivity |

`auto` search mode picks title search for short queries (≤2 words, ≤30 chars) and hybrid retrieval for longer semantic queries.

---

## Retrieval System

There are **two retrieval stacks** — one live in the production API, one more advanced but not yet connected.

### 1. Production path — `app/rag/` (used by `/query` and hybrid movie search)

**`rag/retriever.py`** — Single SQL query fusing:

- **Dense**: pgvector cosine distance on `chunks.embedding`
- **Sparse**: Postgres FTS via `websearch_to_tsquery` on `search_vector`
- **Fusion**: Reciprocal Rank Fusion (RRF, k=60) inside SQL

Also exposes `retrieve_dense()` as a baseline for eval.

**`rag/sparse.py`** / **`rag/hybrid.py`** — Alternate Python-side sparse + RRF implementations (parallel code paths, not the primary `/query` path).

**`rag/generator.py`** — Formats chunks into a numbered context block, calls Cerebras with a strict “answer only from context” system prompt.

### 2. Next-gen path — `app/retrieve/` + `app/graph/` (built, not wired to `/query`)

A **three-source** retrieval design:

| Source | Module | What it does |
|--------|--------|--------------|
| Vector | `retrieve/hybrid_retriever.py` | Dense nearest-neighbor |
| FTS | reuses `rag/sparse.py` | Keyword match |
| Graph | `retrieve/graph_retriever.py` | Structural SQL over join tables |

**`retrieve/fusion.py`** — Weighted RRF across sources (graph weighted 2.0, vector 1.0, FTS 0.8). `retrieve_and_fuse()` is the intended unified entry point.

**Graph layer:**

- **`graph/entities.py`** — Extracts people, movies, genres, keywords from queries using n-grams + `pg_trgm` similarity
- **`graph/router.py`** — Rule-based intent detection (filmography, intersection, “movies like X”, tag filters, connection paths) → dispatches to query templates
- **`graph/queries.py`** — SQL for filmography, set intersections, shared-entity similarity, BFS paths between people

---

## Project Structure

```
app/
├── main.py              # FastAPI app, CORS, health check
├── config.py            # Settings from .env
├── db.py                # Async psycopg connection helper
├── api/
│   ├── query.py         # POST /query
│   └── movies.py        # Browse, search, detail, genres
├── ingest/
│   ├── pipeline.py      # TMDB → Postgres
│   ├── chunker.py       # Movie → text chunk
│   ├── embedder.py      # BGE embeddings
│   ├── store.py         # Chunk + vector persistence
│   └── tmdb_client.py   # TMDB HTTP client
├── rag/
│   ├── retriever.py     # Production hybrid retrieval (SQL RRF)
│   ├── sparse.py        # FTS retriever
│   ├── hybrid.py        # Python-side hybrid fusion
│   └── generator.py     # Cerebras answer generation
├── graph/
│   ├── entities.py      # Query → structured entities
│   ├── router.py        # Intent detection + query dispatch
│   └── queries.py       # Graph traversal SQL
├── retrieve/
│   ├── hybrid_retriever.py
│   ├── graph_retriever.py
│   └── fusion.py        # Multi-source weighted RRF
└── utils/
    └── tmdb.py          # TMDB image URL helpers

sql/01_schema.sql        # Base schema (auto-loaded by Docker)
migrations/              # FTS, graph indexes, pg_trgm
scripts/                 # run_ingest, run_embed, test scripts
eval/                    # Ragas evaluation against live /query
```

---

## Evaluation

Run with the API live on port 8000:

```bash
python -m eval.run
```

Scoring: [Ragas](https://github.com/vibrantlabsai/ragas) — faithfulness, answer relevancy, context precision, context recall. Judge: `llama-3.3-70b-versatile` via Groq. Embedder: `bge-small-en-v1.5` local.

| Retrieval strategy | Faithfulness | Answer Relevancy | Context Precision | Context Recall | Movie Recall |
|---|---|---|---|---|---|
| Naive vector (Day 3) | 0.971 | 0.772 | 1.000 | 0.875 | 0.660 |

*NaN on relational + comparative categories — naive vector retrieval fails to find useful context for cross-entity and set-operation queries. Graph retrieval (Day 5) targets this gap.*

---

## Authentication

Email/password auth with short-lived JWT access tokens and opaque refresh tokens stored server-side (hashed in Postgres).

| Endpoint | Purpose |
|----------|---------|
| `POST /auth/register` | Create account |
| `POST /auth/login` | Returns `access_token` + `refresh_token` |
| `POST /auth/refresh` | Rotate refresh token, issue new pair |
| `POST /auth/logout` | Revoke refresh token |
| `GET /auth/me` | Current user (requires Bearer access token) |
| `GET /auth/admin/ping` | Admin-only health check |

Login and register are rate-limited (default `5/minute` per IP via `LOGIN_RATE_LIMIT`).

Users have a `role` column (`user` or `admin`). Use `require_admin` dependency for protected admin routes.

### Token storage (frontend)

Access and refresh tokens are stored in `localStorage` and sent as `Authorization: Bearer <access_token>`.

**CSRF:** Not applicable — the browser does not auto-send Bearer tokens on cross-site requests.

**XSS (primary risk):** Any injected script can read `localStorage`. Mitigations in this project:
- 15-minute access token TTL
- Refresh token rotation with server-side revocation on logout
- Reuse of a revoked refresh token revokes all tokens for that user

For production, add a strict Content-Security-Policy at the reverse proxy or middleware layer.

**Cookies vs Bearer header:** httpOnly cookies would reduce XSS token theft but require CSRF protection (`SameSite=Strict` + CSRF tokens). This project uses Bearer + localStorage for simplicity.

### JWT secret rotation

If `JWT_SECRET_KEY` is compromised, rotate without immediately invalidating all sessions:

1. Set `JWT_SECRET_KEY_PREVIOUS` to the current `JWT_SECRET_KEY`.
2. Generate a new `JWT_SECRET_KEY` and deploy.
3. New tokens are signed with the new key; existing access tokens verify against the previous key until they expire (max ~access TTL + refresh TTL).
4. After the grace window, clear `JWT_SECRET_KEY_PREVIOUS`.

Access tokens include `iss` (`movie-rag`) and `aud` (`movie-rag-api`) claims; both are validated on decode.

---

## Design Choices

1. **Postgres as the single store** — relational movie graph, vectors, and FTS all in one DB; no separate vector DB.
2. **One chunk per movie** — simple indexing; graph retriever fetches chunks for structurally matched movies.
3. **Rule-based graph routing** — deterministic, fast, debuggable; upgrade path to LLM-based planning is documented in code.
4. **Grounded generation** — LLM is constrained to retrieved context; low temperature (0.3).
5. **Incremental evolution** — `app/rag/` is what ships today; `app/retrieve/` + `app/graph/` are the Day 5+ architecture waiting to be plugged into `/query`.
