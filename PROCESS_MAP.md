# Movie-RAG — End-to-End Process Map

How data flows from **TMDB → Postgres → embeddings → user query → grounded answer**.
There are two distinct phases: an **offline ingestion/indexing** phase (run by scripts), and an
**online query** phase (served by FastAPI on every `POST /query`).

---

## Phase A — Offline: Build the knowledge base

Run once (and again when the catalog changes):
```
python scripts/run_ingest.py     # TMDB  -> Postgres tables
python scripts/run_embed.py       # chunk text -> vectors + FTS
```

### A1. Ingest — TMDB → Postgres  (`app/ingest/pipeline.py`)

```
TMDB API
  │  discover_movies()           collect candidate movie IDs (paged)
  ▼
_collect_movie_ids(cap)
  │  _load_existing_ids()        skip IDs already in DB (idempotent)
  ▼
_fetch_all_details()             concurrent detail fetches, 50 per wave
  │  get_movie_details(id)       full TMDB record per movie
  ▼
_load_into_db()
  └─ _upsert_movie(conn, m)      parse one movie dict, INSERT into all tables:
                                 movies, genres, people (cast/crew),
                                 keywords, and their join tables
```
Result: normalized movie data sits in Postgres. **No vectors yet.**

### A2. Chunk — one text blob per movie  (`app/ingest/chunker.py`)

```
build_chunks(conn)               SELECT movie + joined genres/cast/crew/keywords
  └─ _format_movie(row)          flatten into ONE rich text string per movie
                                 (title, year, overview, directors, top writers,
                                  top 5 cast, genres, keywords)
  ▼
[(movie_id, chunk_text), ...]    exactly one chunk per movie, chunk_type = 'full'
```
> Landmine: editing a movie's text does **not** re-embed automatically — rerun `run_embed.py`.

### A3. Embed + index — text → vector + FTS  (`scripts/run_embed.py`, `app/ingest/embedder.py`)

```
embed_and_store()
  │  build_chunks() / build_chunks_missing()      get (movie_id, text) pairs
  ▼
embed_texts(texts, batch_size=64)                 SentenceTransformer
  │      model = BAAI/bge-small-en-v1.5  -> 384-dim vectors (normalized)
  ▼
write each chunk row into  chunks:
   • chunk_text       the flattened movie text
   • embedding        vector(384)         -> HNSW index (pgvector, cosine)
   • search_vector    tsvector            -> GIN index (Postgres FTS)
```
After A3 the `chunks` table is fully searchable on **both** semantic (vector) and
lexical (full-text) axes. `--full-rebuild` wipes and re-embeds everything.

---

## Phase B — Online: Answer a user query  (`POST /query`)

Entry point: `app/api/query.py` → `retrieve` → `generate`.

```
                       ┌──────────────────────────────────────────────┐
  user question  ───►  │  POST /query   {question, k, include_chunks}  │
                       └──────────────────────────────────────────────┘
                                          │
                                          ▼
                   ┌─────────────────────────────────────────┐
                   │  B1. retrieve(question, k)               │   app/rag/retriever.py
                   └─────────────────────────────────────────┘
                                          │
        embed_query_async(question)  ─────┤  "query:"-prefixed text -> 384-dim vector
                                          │  (bge query prefix; cached; run off-thread)
                                          ▼
                   ┌──────────────── single SQL statement ───────────────┐
                   │                                                      │
                   │  vector_search (CTE)        fts (CTE)                │
                   │  ORDER BY embedding <=> vec  websearch_to_tsquery    │
                   │  HNSW cosine, ranked        ts_rank, GIN, ranked     │
                   │            │                       │                 │
                   │            └────────► fused ◄───────┘                │
                   │   rrf = 1/(60+rank_vec) + 1/(60+rank_fts)            │
                   │   ORDER BY rrf_score DESC  LIMIT k                   │
                   └──────────────────────────────────────────────────────┘
                                          │
                                          ▼
                         List[RetrievedChunk]  (top-k movies + scores + text)
                                          │
                  if empty ──►  raise HTTPException 404                      (guard in
                                "No relevant movies found." stop              endpoint,
                                          │                                   NOT augmentation)
                                          ▼
                   ┌─────────────────────────────────────────┐
                   │  B2. AUGMENT  format_context(chunks)     │   app/rag/generator.py
                   └─────────────────────────────────────────┘
                                          │  inject top-k chunks into the prompt:
                                          │  numbered context block (1..k)
                                          ▼
                   ┌─────────────────────────────────────────┐
                   │  B3. GENERATE  generate(question, ctx)   │   app/rag/generator.py
                   └─────────────────────────────────────────┘
                                          │
                   AsyncOpenAI client → Cerebras  (gpt-oss-120b)
                     system = strict grounding prompt
                              "answer ONLY from numbered context"
                     temperature = 0.3  (grounded, not creative)
                                          │
                                          ▼
                   ┌─────────────────────────────────────────┐
                   │  B4. QueryResponse                       │
                   │    { answer, retrieved:[{movie, score,   │
                   │       chunk_text?}] }                    │
                   └─────────────────────────────────────────┘
                                          │
                                          ▼
                                    response to user
```

### Step detail

| Step | Where | What happens |
|------|-------|--------------|
| **B1a Embed query** | `embedder.embed_query_async` | Prefix with `query:`, encode with bge → 384-dim vector (cached, off-thread). |
| **B1b Hybrid search** | `retriever.retrieve` (one SQL) | Two candidate searches run together: **dense** (`embedding <=> vec`, HNSW/cosine) and **lexical** (`websearch_to_tsquery` + `ts_rank`, GIN). |
| **B1c RRF fusion** | same SQL, `fused` CTE | Each candidate scored `1/(60+rank_vec) + 1/(60+rank_fts)`; ranking on both lists wins. Sort by `rrf_score`, take top-k. |
| **Empty guard** | `api/query.py` (`if not chunks`) | If retrieval returns nothing, raise **HTTP 404 "No relevant movies found."** — augmentation/generation are skipped entirely. |
| **B2 Augment** | `generator.format_context` | The **A** in RAG: top-k chunks injected into the prompt as a numbered context block. Only runs when chunks exist. |
| **B3 Generate** | `generator.generate` | Cerebras LLM answers **only** from that context, low temperature (0.3), citing title+year. |
| **B4 Respond** | `api/query.py` | Returns `answer` + `retrieved` (scores; `chunk_text` only if `include_chunks=true`). |

### Two retrieval entry points (same engine)
- `retrieve()` → returns full chunks for `/query` (Q&A).
- `retrieve_movie_rankings()` → returns movie IDs + scores only, for hybrid movie search (`app/api/movies.py`).
- `retrieve_dense()` → dense-only baseline (cosine, no FTS/RRF).

---

## One-line summary
**Offline:** TMDB → upsert into Postgres → flatten to one text chunk/movie → embed (bge-384) + FTS index.
**Online:** embed the question → single-SQL dense + FTS search fused by RRF → top-k → Cerebras answers strictly grounded in those chunks → return answer + sources.
