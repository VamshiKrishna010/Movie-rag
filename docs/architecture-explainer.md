# Movie-RAG: Architecture Explainer

A walk through the system from top to bottom: what each piece does, why it's there, and how a single user query flows from the browser to a grounded answer.

Intended for someone who knows general backend / SQL but hasn't seen this codebase.

---

## 1. The stack at a glance

```
Browser (React + Vite, :5173)
        │  HTTP/JSON
        ▼
FastAPI app (Uvicorn, :8000)
        │  async psycopg
        ▼
PostgreSQL 16  +  pgvector  +  FTS (built-in)
                                                │
                                                └── one DB, two retrieval signals
LLM:        Groq  (OpenAI-compatible client)  — answer generation
Embedder:   sentence-transformers  BAAI/bge-small-en-v1.5  (local)
```

Two processes during development: the **backend** (`uvicorn app.main:app --reload --app-dir .`) and the **frontend** (`cd frontend && npm run dev`). They run independently; the browser loads the UI from Vite and makes API calls to FastAPI. CORS is configured to allow `http://localhost:5173`.

---

## 2. What each layer does

### 2.1 FastAPI

The web framework. Gives you:

- Route decorators (`@app.post("/query")`) so functions become HTTP endpoints.
- Pydantic-based request/response validation — invalid input is rejected before handlers run.
- Auto-generated OpenAPI docs at `/docs`.
- Dependency injection (`Depends(...)`) for `get_current_user`, scope checks, DB-pool injection.
- ASGI / async-native — runs thousands of concurrent requests on one process without threads.

### 2.2 `async` / `await`

Python's cooperative concurrency.

- `async def` declares a coroutine.
- `await` is the point where it can pause and let other work run while waiting on I/O.

Why this project needs it:

1. **Database calls.** `psycopg.AsyncConnection` — `await cur.execute(...)` releases the event loop while Postgres works.
2. **LLM calls.** The slowest part of a `/query` request is the Groq HTTP call; `await` lets other requests progress during that wait.
3. **Concurrent retrievers.** `asyncio.gather(hybrid, graph)` runs the two retrieval stacks in parallel — wall-time = max(both), not sum.
4. **Pool bookkeeping.** `asyncio.Lock` serializes pool operations without blocking the event loop.

Rule of thumb in this codebase: any function that does I/O is `async def`, every call to it is `await`ed. CPU-only helpers stay sync.

### 2.3 `asyncio`

The standard library that *runs* `async`/`await` code:

- The **event loop** (uvicorn owns it).
- Primitives: `gather`, `wait_for`, `create_task`, `Lock`, `Semaphore`, `Queue`, `sleep`.
- Bridges: `to_thread` for running blocking code without freezing the loop.

`async`/`await` are syntax; `asyncio` is the runtime. You can't have one without the other.

### 2.4 CORS

Browser security rule. JS on `http://localhost:5173` cannot call `http://localhost:8000` by default — different origin (scheme+host+port). The server has to opt in by sending `Access-Control-Allow-Origin: http://localhost:5173`. Configured in `app/main.py` via `CORSMiddleware`, reading `CORS_ORIGINS` from `.env`.

Two wrinkles handled:
- **Preflight `OPTIONS`** for non-simple requests (auth headers, JSON) — `CORSMiddleware` handles automatically.
- **Credentials** (the `mr_refresh` cookie) — requires `Access-Control-Allow-Credentials: true` and a *specific* origin (never `*` with credentials).

In production with a single origin (frontend + backend behind one domain), CORS goes away.

---

## 3. The database

PostgreSQL 16, run via `docker-compose.yml`. Schema in `sql/01_schema.sql`, ordered changes in `migrations/NNN_*.sql`.

### 3.1 Extensions

| Extension | Role |
|---|---|
| `vector` (pgvector) | 384-dim semantic embeddings + HNSW index |
| `pg_trgm` | Optional trigram indexes for title/name search |
| FTS | Built into Postgres (no extension) — tokenize/stem/index English text |

### 3.2 Content tables

```
movies ─┬─< movie_people >─ people
        ├─< movie_genres >─ genres
        ├─< movie_keywords >─ keywords
        └─< chunks
```

- **`movies`** — ~9,999 rows. Primary key is the TMDB id. Stores `title`, `release_year`, `overview`, `tagline`, `runtime`, `vote_average`, and the full TMDB payload in `raw JSONB`.
- **`people`** — directors, actors, writers.
- **`movie_people`** — cast/crew join with `role ∈ {director, actor, writer}` and `cast_order` for actors.
- **`genres`, `movie_genres`** — many-to-many.
- **`keywords`, `movie_keywords`** — many-to-many (TMDB tag keywords).
- **`chunks`** — the retrieval table. **Multiple rows per movie** (`chunk_type = 'full'`, plot-focused `plot`, and heuristic `themes`). Columns:
  - `content TEXT` — the text fed to the embedder; also what the LLM eventually reads.
  - `embedding vector(384)` — BGE output.
  - `tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED` — auto-maintained FTS column.

### 3.3 Auth tables (migrations 008–010)

- **`users`** — `id`, `email UNIQUE`, `hashed_password` (bcrypt), `role ∈ {user, admin}` (CHECK-constrained).
- **`refresh_tokens`** — opaque server-side refresh tokens. Stores only `token_hash`, never the raw token. Has `expires_at` and `revoked_at` (for rotation/reuse detection). Backs the "stateful refresh, stateless access" pattern: short-lived JWTs for API calls, DB-backed tokens for renewal.

### 3.4 Indexes (the why)

| Index | Purpose |
|---|---|
| `chunks_embedding_hnsw_idx` (HNSW, cosine) | Semantic vector search. Built **after** embeddings exist. |
| `chunks_tsv_idx` (GIN) | FTS — fast `@@` matches against tokenized content. |
| `*_trgm` GIN indexes on `movies.title`, `people.name`, etc. | Fuzzy / typo-tolerant lookup; powers entity extraction. |
| `movie_people_*` composite indexes | Graph traversal: person→films, film→co-stars. |
| `movie_genres_*`, `movie_keywords_*` | Same-genre / shared-keyword expansion. |
| `refresh_tokens_hash_idx` | O(log n) lookup on every refresh. |

### 3.5 Migrations

Versioned, ordered SQL files that evolve the schema after the base `sql/01_schema.sql` is applied.

```
migrations/
  004_fts.sql                # tsvector + GIN on chunks
  005_graph_indexes.sql      # optional relational metadata indexes
  006_pg_trgm.sql            # optional pg_trgm + trigram indexes
  007_hnsw.sql               # HNSW vector index (after embeddings exist)
  008_users.sql              # users table
  009_auth_hardening.sql     # users.role + refresh_tokens
  010_user_role_check.sql    # CHECK on users.role
```

Rules:

1. **Never edit an applied migration.** Add a new one (`011_*.sql`).
2. **Idempotent where possible** — `CREATE ... IF NOT EXISTS`, conditional `ADD COLUMN`.
3. **Forward-only.** No down migrations.
4. **One concern per file.**
5. **Order matters** (e.g. HNSW after embeddings).

No migration tool is in use; CI re-applies base + migrations in order against a fresh container, which works because the SQL is idempotent.

---

## 4. The two pieces of text-as-data, side by side

Both columns live on `chunks` and both index the same `content`, but they serve different match modes:

### 4.1 `embedding vector(384)` — dense / semantic

Built at ingest time by running `content` through `sentence-transformers` with `BAAI/bge-small-en-v1.5`. That model uses a **BERT WordPiece tokenizer** internally (via HuggingFace's `tokenizers` Rust crate) — `tiktoken` is *not* used anywhere in this project. The output is a 384-dim float vector that's L2-normalized.

Stored in the `embedding` column, indexed by HNSW with cosine distance. At query time, the user's query is embedded the same way and matched by `embedding <=> $query_vec`.

### 4.2 `tsv tsvector` — sparse / lexical / FTS

Built at write time by Postgres's `english` text parser. For the text `"The Shawshank Redemption is about prisons and friendship."`, the `tsvector` is:

```
'friendship':8 'prison':6 'redempt':3 'shawshank':2
```

Four things happened:
1. **Tokenize** — split on whitespace/punctuation.
2. **Lowercase** + **drop stopwords** (`the`, `is`, `about`, `and`).
3. **Stem** with Snowball English (`redemption` → `redempt`, `prisons` → `prison`).
4. **Encode** as a sorted list of lexemes with their positions.

A **lexeme** is the normalized base form. `prisons`, `prison`, `prison's` all stem to lexeme `'prison'`. Stored, indexed, never returned to the app — exists only to make text searchable.

### 4.3 Dense vs sparse — what each is good and bad at

| | Dense / semantic | Sparse / FTS |
|---|---|---|
| Matches by | meaning | stemmed words |
| Operator | `embedding <=> $1::vector` | `tsv @@ plainto_tsquery('english', $1)` |
| Index | HNSW | GIN |
| Synonyms ("jail" ↔ "prison") | yes | no — different lexemes |
| Typos ("redmption") | partial | no |
| Exact titles ("Godfather") | weak | strong |
| Conceptual queries ("feel-good 80s comedies") | strong | weak |
| Explainability | low | high |
| Speed | ms with HNSW | ms with GIN |
| Cost to build | slow (ML model per row) | cheap (pure Postgres) |

Neither wins on its own. That's why this project fuses them.

### 4.4 `pg_trgm` — character-level fuzzy

Breaks strings into overlapping 3-character chunks. `"shawshank"` → `{"  s", " sh", "sha", "haw", "aws", "wsh", "sha", "han", "ank", "nk ", "k  "}`. Two strings are similar if their trigram sets overlap.

Uses:
- Typo-tolerant search (`"shawshnk"` still finds Shawshank).
- Substring matches (`"god father"` matches `"Godfather"`).
- Fast `ILIKE '%foo%'` even with a leading wildcard.

Indexed by `gin (col gin_trgm_ops)`. Powers entity extraction in `app/graph/entities.py` — `"tom hanx"` → `Tom Hanks`.

### 4.5 GIN index

**GIN = Generalized Inverted iNdex.** Built for columns holding multiple values per row (arrays, JSONB, tsvectors, trigrams).

Structure (conceptually):
```
value     → list of row IDs
prison    → [42, 91, 188, ...]
redempt   → [42, 510, ...]
shawshank → [42]
```

Same idea as a book's index: term → pages. Slow to write, fast to read. Perfect for chunks (write once, search many times).

### 4.6 HNSW index

**HNSW = Hierarchical Navigable Small World.** Built for approximate nearest-neighbor search in high-dimensional vector space. Exact cosine comparison would be O(n) — comparing a query vector against every row. HNSW gets to roughly O(log n) by building a multi-layer graph at index time.

Structure (conceptually):

```
Layer 2 (sparse):   A ————————— F
                    |           |
Layer 1 (medium):   A — C — D — F — H
                    |   |   |   |   |
Layer 0 (dense):    A-B-C-D-E-F-G-H-I-J   ← all vectors live here
```

**Search**: start at the top layer, greedily move toward the query vector, drop to the next layer, repeat. You converge fast because upper layers let you skip large distances in one hop.

**Insert**: each new vector is assigned a random max layer. It connects to its nearest neighbors at each layer it participates in, bounded by `m` connections per node.

Tuning knobs (from `migrations/007_hnsw.sql`):

```sql
WITH (m = 16, ef_construction = 64)
```

- `m = 16` — max connections per node per layer; higher = better recall, more memory and slower build.
- `ef_construction = 64` — search width used *during index build*; higher = better graph quality, slower index creation.

The `<=>` operator in queries (`ORDER BY embedding <=> $1::vector`) triggers the HNSW index automatically via pgvector. The result is approximate — a tiny fraction of truly nearest neighbors may be missed — but in practice recall is high and the speed gain is dramatic.

---

## 5. The retrieval stack

This project has **two** retrieval signals in the primary path. Both run against the same DB and return ranked chunk/movie IDs.

### 5.1 Dense retriever (semantic)

```sql
SELECT movie_id, 1 - (embedding <=> $1::vector) AS score
FROM chunks
ORDER BY embedding <=> $1::vector
LIMIT 50;
```

User query → BGE encode → 384-dim vector → cosine search via HNSW.

### 5.2 Sparse retriever (FTS)

```sql
SELECT movie_id, ts_rank(tsv, q) AS score
FROM chunks, plainto_tsquery('english', $1) q
WHERE tsv @@ q
ORDER BY score DESC
LIMIT 50;
```

Tokenize query the same way docs were tokenized → look up lexemes in the GIN index → intersect → rank by `ts_rank` (which considers term frequency and rarity).

### 5.3 Hybrid fusion — Reciprocal Rank Fusion (RRF)

Each retriever produces a ranked list with its own scoring scale (cosine 0–1, `ts_rank` unbounded floats). You can't add them directly — they live in different universes.

**RRF throws the scores away and uses ranks:**

```
score(doc) = Σ over retrievers   1 / (k + rank_in_that_retriever)
```

`k ≈ 60`, `rank = 1` for top-1, 2 for top-2, etc. Docs missing from a retriever contribute 0.

Example — a doc ranked 1 in dense and 3 in FTS:

```
score = 1/(60+1) + 1/(60+3) = 0.0164 + 0.0159 = 0.0323
```

Sort all docs by total score, take top-K.

Why RRF:
1. Score-scale-agnostic — only ranks matter.
2. Robust to outliers — the `1/(k+rank)` curve flattens fast.
3. Docs found by multiple retrievers float up automatically.
4. Zero training data needed.
5. Keeps dense and sparse ranking behavior comparable without tuning raw scores.

### 5.4 The retrieval stack in this codebase

One stack is live:

| Stack | Where | What `POST /query` does |
|---|---|---|
| **Single-SQL hybrid** | `app/rag/retriever.py` | Runs dense vector search and sparse FTS, then fuses ranks with RRF |

There used to be a "naive vector" baseline (Day 3 in the README's Ragas table) — that's *not* in the live code path, only in the eval table for comparison.

---

## 6. The three letters of RAG, in this project

```
R — Retrieval     →  app/rag/retriever.py
A — Augmentation  →  app/rag/generator.py (prompt assembly)
G — Generation    →  app/rag/generator.py (Groq call)
```

### 6.1 Retrieval

Find chunks that might answer the question. Covered above. Output: a ranked list of chunk IDs + scores. **The embedding model only runs here** (and at ingest time). The LLM is not involved.

### 6.2 Augmentation

**Build the prompt that the LLM will see.** Pure string manipulation — no model, no embeddings, no ML.

```python
def build_prompt(query: str, chunks: list[Chunk]) -> list[dict]:
    context = "\n\n".join(f"[{i+1}] {c.content}" for i, c in enumerate(chunks))
    return [
        {
            "role": "system",
            "content": (
                "You are a movie expert. Answer ONLY using the context below. "
                "If the answer isn't there, say you don't know. Cite sources by [n]."
            ),
        },
        {
            "role": "user",
            "content": f"Context:\n{context}\n\nQuestion: {query}",
        },
    ]
```

Steps inside augmentation:
1. SQL `SELECT content FROM chunks WHERE id IN (...)` to fetch text for the retrieved IDs.
2. Format each chunk with a source marker (`[1]`, `[2]`, ...) so the model can cite.
3. Truncate to a token budget — can't dump 50 chunks into a finite context window.
4. Order by score; LLMs attend more to start/end of context.
5. De-duplicate (same chunk surfaced by multiple retrievers).
6. Wrap with the **grounding system prompt** — the instruction to use only the provided context.

Augmentation is where most production RAG systems silently fail: too many chunks (noise), bad order (lost-in-the-middle), weak grounding instruction (model ignores context). A great retriever + a mediocre prompt = mediocre answers.

### 6.3 Generation

Send the prompt to the LLM and return its answer.

```python
resp = await client.chat.completions.create(
    model="llama-3.3-70b-versatile",  # Groq
    messages=messages,
    max_tokens=350,
    temperature=...,              # low, to stay grounded
)
return resp.choices[0].message.content
```

Groq runs an OpenAI-compatible API; the SDK is the standard `openai` Python client. The LLM tokenizes the prompt server-side using `llama-3.3-70b-versatile`'s own tokenizer — *not* tiktoken, not BGE's WordPiece. The model predicts the next token repeatedly until `max_tokens` or a stop token.

Knobs:
- `temperature` — randomness. Low (0–0.3) for grounded RAG; this project uses low.
- `max_tokens` — hard cap on the answer (350 here).
- `model` — which weights to use.
- `stop` — optional sequences that halt generation.

### 6.4 Why generation is the *last* step, not the *main* step

In a pure LLM app (no RAG) the model answers from its training. In RAG, generation is mostly a **synthesis** step: "Given these 5 chunks, phrase a coherent answer; don't invent facts."

Retrieval quality dominates answer quality. If retrieval surfaces the right chunks, even a small LLM produces a fine answer. If retrieval misses, no model intelligence saves you.

### 6.5 Naive RAG vs hybrid RAG

| Name | What it is | This project |
|---|---|---|
| Naive RAG | One retriever (usually dense), stuff top-K in the prompt | Day-3 baseline, only in eval table |
| **Hybrid RAG** | Dense + sparse fused | `app/rag/retriever.py` — the live `/query` path |
| Graph RAG | Retrieval over a knowledge graph | Not used |
| Agentic RAG | LLM decides which retrievers to call, iterates | Not used |
| Self-RAG / CRAG | LLM critiques retrieved chunks, re-retrieves if bad | Not used |

The accurate one-line label for this system: **"Hybrid RAG over a Postgres-only stack, with dense and FTS ranks merged by RRF."**

"Naive" is not a pejorative — it's the standard term in the RAG literature for the textbook minimal pipeline, the same way "naive Bayes" is a real algorithm with that name.

---

## 7. End-to-end: a single `POST /query`

```
1.  Browser → POST /query  { question: "movies about hope in prison" }

2.  FastAPI auth dependency → extract user (optional for this endpoint)

3.  app/rag/retriever.py embeds the query with BGE

4.  Single SQL retrieves dense vector candidates and sparse FTS candidates

5.  SQL RRF merge ranks the candidates and returns top-K chunks

6.  generator.py:
       ├── augment: build messages = system prompt + context + question
       └── generate: await Groq chat.completions.create(...)

7.  Return JSON { answer, sources }  → browser
```

Steps 4 and 6 are the slow ones. Step 4 includes local query embedding plus Postgres retrieval. Step 6 is the single biggest latency contributor (LLM round-trip).

---

## 8. The three tokenizers in play (none of them are the same)

| Layer | Tokenizer | Where it runs |
|---|---|---|
| Embeddings (ingest + query) | BERT WordPiece (BGE) | Local Python, via `sentence-transformers` + `tokenizers` |
| FTS | Postgres `english` parser + Snowball stemmer | Inside Postgres (C) |
| LLM generation | `llama-3.3-70b-versatile`'s own tokenizer | Server-side at Groq |

`tiktoken` is **not used anywhere** — it's OpenAI's BPE tokenizer for GPT models; this project uses different models for both embedding and generation.

These three never share tokens — that's fine, because they never compare to each other. The embedding tokenizer's output is a 384-dim vector that only pgvector reads; the LLM only sees the original English text in `chunks.content`.

---

## 9. Where to edit what

| To change… | Go to |
|---|---|
| `/query` retrieval / movie-search hybrid | `app/rag/retriever.py` |
| Answer generation / grounding prompt | `app/rag/generator.py` |
| Movie browse / search / detail endpoints | `app/api/movies.py` |
| Auth endpoints (login/refresh/logout/me) | `app/api/auth.py` + `app/auth/` |
| Roles, scopes, route guards | `app/auth/scopes.py`, `app/auth/deps.py` |
| Admin API / dashboard backend | `app/api/admin.py`, `app/admin/` |
| TMDB fetch → Postgres ingestion | `app/ingest/` |
| Chunk text per movie | `app/ingest/chunker.py` (then re-embed) |
| DB connection / pool | `app/db.py` |
| Settings / env vars | `app/config.py` |
| Graph intent routing / entity extraction | `app/graph/router.py`, `app/graph/entities.py` |
| Frontend pages / API clients | `frontend/src/pages/`, `frontend/src/api/` |

---

## 10. Things to know that aren't obvious from the code

1. **`app/config.py` validates at import.** `JWT_SECRET_KEY` must be ≥32 chars and non-default, or the app refuses to start. Intentional guardrail.
2. **Multiple chunks per movie** today (`chunk_type = 'full'`, `plot`, and `themes`). Manual movie text edits do *not* re-embed — re-run `scripts/run_embed.py` after changes. If only theme rules changed, run `scripts/run_embed.py --refresh-types themes`.
3. **Schema changes go in a new numbered `migrations/NNN_*.sql`** — never edit the base schema retroactively.
4. **Generation must stay grounded** — the system prompt restricts the LLM to the retrieved context. Don't loosen it.
5. **Tests hit a real Postgres** — no mocking layer. CI spins up a `pgvector/pgvector:pg16` container and loads schema + migrations before running pytest.
6. **Two retrieval stacks both live.** Fusion is primary; single-SQL hybrid is the fallback. Both serve real traffic.
7. **Two tsvector columns currently exist on `chunks`** — `tsv` from `01_schema.sql` and `search_vector` from migration 004. Worth checking whether both are still queried; if not, one can be dropped.

---

## 11. One-paragraph executive summary

This is a movie Q&A backend that turns a user question into a grounded answer by combining two retrieval signals: semantic vector search over BGE embeddings with pgvector/HNSW and keyword full-text search over Postgres `tsvector` columns with GIN indexes. The system merges ranked outputs with Reciprocal Rank Fusion, then injects the top chunks into a strictly grounded LLM prompt. Groq's `llama-3.3-70b-versatile` model generates the final answer using only the retrieved context.

The architecture is hybrid RAG: more robust than a naive vector-only pipeline because it handles conceptual movie queries and exact keyword/name lookups in the same retrieval path. Auth, ingestion, evaluation with Ragas, and a React frontend round out the system. The stack is built on Postgres, FastAPI, pgvector, and async Python.

---

## 12. Auth stack

### 12.1 Libraries

| Library | Role |
|---|---|
| `bcrypt` | Password hashing (`bcrypt.hashpw` / `checkpw`) |
| `python-jose` (`jose`) | JWT creation and decoding (`HS256`) |
| `authlib` | Google OAuth2 client (`authlib.integrations.starlette_client`) |
| FastAPI `OAuth2PasswordBearer` | Extracts `Bearer <token>` from incoming requests |

### 12.2 Internal modules (`app/auth/`)

| File | Responsibility |
|---|---|
| `security.py` | Hash/verify passwords; create/decode JWTs; JWT key rotation support |
| `refresh.py` | Opaque refresh token lifecycle — issue, rotate, revoke, reuse detection |
| `cookies.py` | Set/clear the HttpOnly `mr_refresh` cookie |
| `deps.py` | FastAPI route dependencies — validates Bearer token, injects current user |
| `scopes.py` | Role → scope mapping (e.g. `admin` gets all scopes) |
| `users.py` | DB queries for user lookup by email |
| `google_auth.py` | Authlib OAuth client configured for Google |
| `google_routes.py` | `/auth/google/login` and `/auth/google/callback` endpoints |

### 12.3 What is a JWT?

A JWT (JSON Web Token) is a signed, self-contained proof of identity. It looks like:

```
eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyQGV4YW1wbGUuY29tIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c
  HEADER                PAYLOAD                                  SIGNATURE
```

Three Base64-encoded parts separated by dots:
- **Header** — signing algorithm (`HS256`)
- **Payload** — claims: user email (`sub`), expiry (`exp`), roles, etc.
- **Signature** — HMAC of header+payload using `JWT_SECRET_KEY`

Anyone can *read* the payload (it's just Base64), but no one can *forge* a valid signature without the secret. On every API request the server verifies the signature only — no DB lookup required.

### 12.4 Two-token session design

```
Login
  → server issues: access JWT (expires 15 min)
                 + refresh token (HttpOnly cookie, expires 30 days)

Every API call
  → client sends: Authorization: Bearer <access_jwt>
  → server verifies signature → done (no DB hit)

Access token expires
  → client sends refresh cookie → server issues new access JWT + rotates refresh token
```

The short 15-minute JWT limits damage if a token is stolen — it goes stale quickly. The refresh token handles longer sessions safely.

### 12.5 Refresh token storage (never raw)

Refresh tokens are **random 32-byte URL-safe strings** (`secrets.token_urlsafe(32)`). The raw token is only ever held by the client in the HttpOnly cookie. The server stores only its **SHA-256 hash** in Postgres. If the DB is compromised, the attacker gets hashes — unusable without the original tokens.

### 12.6 Refresh token reuse detection

Every refresh rotates the token: the old hash is marked **revoked**, a new token is issued. When the server receives a refresh request it checks:

1. Hash the incoming token
2. Look it up in the DB
3. If found and **active** → rotate normally
4. If found but **revoked** → **theft detected**

On detecting a revoked token being reused, the server calls `_revoke_all_user_tokens()` — it nukes every refresh token for that user across all devices. This is **token family revocation**: one suspicious event forces a full re-login everywhere.

Why this is strong: even if an attacker steals a refresh token and uses it first, the moment the real user's copy is rejected, all tokens the attacker obtained are also killed immediately.

### 12.7 Cookie hardening

The `mr_refresh` cookie is set with:
- **`HttpOnly`** — JavaScript cannot read it (XSS protection)
- **`SameSite=lax`** (`none` in split-origin prod) — CSRF protection
- **`Path=/auth`** — cookie is only sent to `/auth/*` routes, not to `/movies`, `/query`, etc.
- **`Secure=true`** in production — HTTPS only

### 12.8 Google OAuth path

Google login issues the same JWT + refresh pair as password login — the OAuth callback validates the Google ID token, upserts the user in Postgres, then runs the normal token issuance flow.

### 12.9 JWT key rotation

`app/config.py` accepts a `JWT_SECRET_KEY_PREVIOUS` env var. `security.py` tries decoding with the current key first; if that fails it falls back to the previous key. This allows zero-downtime secret rotation: deploy the new key, keep the old one as `_PREVIOUS` for the duration of the longest active access token (15 min), then clear it.
