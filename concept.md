# Movie-RAG — Concepts In Depth

A complete map of every RAG concept this project uses, grounded in the actual code.
Organized by the two phases (offline indexing, online querying) plus cross-cutting ideas.
Each numbered heading is a concept; the bullets under it are its sub-concepts.

---

## The big picture

RAG (Retrieval-Augmented Generation) has two halves that run at different times:

- **Indexing (offline, build the "book")**: `fetch → parse → chunk → embed → store`.
  Run by `scripts/run_ingest.py` + `scripts/run_embed.py`.
- **Querying (online, open-book answer)**: `embed query → retrieve → fuse → augment → generate`.
  Run by `POST /query`.

Everything below is a sub-part of one of those.

---

# PHASE 1 — Indexing (offline)

## 1. Ingestion / fetching
- **Source of truth**: TMDB REST API → raw JSON, cached to `data/raw/movie_*.json`
  (`app/ingest/pipeline.py:108`).
- **Idempotency / incremental load**: `skip_existing` skips IDs already in the DB;
  `ON CONFLICT DO NOTHING` makes re-runs safe. Concept: an indexing pipeline should be
  **re-runnable without duplicating data**.

## 2. Parsing / normalization
- `_upsert_movie` (`app/ingest/pipeline.py:142`) unpacks the nested TMDB JSON into a
  **normalized relational schema**: `movies`, `genres`, `people`, `movie_people`
  (with roles director/writer/actor), `keywords`, join tables.
- **Concept — structured vs unstructured**: you keep both. Structured rows power exact
  filters/browse; the raw JSON is stashed in `movies.raw` as a fallback. RAG sits on top
  of this structured layer.

## 3. Chunking
- **Definition**: a chunk is the retrievable unit — the thing you embed and later feed the LLM.
- **Your strategy — one chunk per movie** (`chunk_type = 'full'`). `_format_movie`
  (`app/ingest/chunker.py:106`) stitches title, directors, writers, cast, genres, tagline,
  overview, keywords into one paragraph.
- **Sub-concepts in chunking:**
  - **Granularity / chunk size** — too big = noisy embeddings & wasted context; too small =
    facts get split apart. One-movie-per-chunk is a deliberate granularity choice that keeps
    each vector "about exactly one movie."
  - **Field selection & ordering** — you don't dump everything; writers capped at 3, cast at
    top-5 billing (`app/ingest/chunker.py:120`, `:125`). Curating what goes in the chunk
    directly shapes retrieval quality.
  - **No overlap needed** — overlap matters when you split long docs; with one self-contained
    chunk per movie it's irrelevant here.

## 4. Embedding (dense vectors)
The heart of semantic search. `embed_texts` (`app/ingest/embedder.py:20`).
- **Embedding model**: `BAAI/bge-small-en-v1.5`, a local `sentence-transformers` model —
  runs on your machine, no API.
- **What it produces**: a fixed **384-dimensional vector** per chunk. Concept: text → a point
  in 384-d space where *meaning ≈ proximity*.
- **Sub-concepts:**
  - **Normalization** (`normalize_embeddings=True`) — scales every vector to length 1, so
    cosine similarity becomes a plain dot product. This is *why* cosine distance is the right
    metric downstream.
  - **Asymmetric embedding (query vs document)** — bge needs a prefix on *queries* only:
    `"Represent this sentence for searching relevant passages: "` (`app/ingest/embedder.py:7`).
    Documents (chunks) get no prefix. This aligns questions and passages in the same space.
    `embed_query` vs `embed_texts` is exactly this split.
  - **Batching** — `batch_size=64`, encode many chunks per GPU/CPU pass for throughput.
  - **Query caching** — `lru_cache(512)` (`app/ingest/embedder.py:40`) so repeated questions
    skip recompute; `embed_query_async` runs it in a thread to not block the event loop.

## 5. Storage in pgvector
- **pgvector** = Postgres extension adding a `vector(384)` column type + similarity operators.
  Your `chunks.embedding` column holds the vectors.
- **Sub-concept — ANN index (HNSW)**: without an index, finding nearest vectors scans every
  row (exact but O(n)). HNSW builds a navigable graph for fast **approximate** nearest-neighbor
  lookup — trades a sliver of recall for big speed. Covered in `docs/architecture-explainer.md`.

## 6. Full-text search index (the sparse / lexical side)
Parallel to embeddings, each chunk also gets a `search_vector` (`tsvector`).
- **Sub-concepts of FTS:**
  - **Tokenization + stemming** — the `'english'` config splits text into lexemes and reduces
    words to roots ("running" → "run").
  - **Stop-word removal** — common words ("the", "a") dropped.
  - **GIN index** — inverted index mapping lexeme → rows, making keyword lookup fast.
- This is the "exact keyword" half that pure semantic search is bad at (e.g. an exact title
  or a rare proper noun).

---

# PHASE 2 — Querying (online) — `POST /query`

## 7. Query embedding
- The question goes through `embed_query_async` → 384-d vector (with the query prefix). Same
  space as the chunks, so distances are comparable.

## 8. Dense retrieval (semantic)
- In SQL: `ORDER BY c.embedding <=> %(vec)s::vector LIMIT candidate_pool`
  (`app/rag/retriever.py:54`).
- **`<=>`** = pgvector cosine distance. Smaller = more semantically similar.
- **Concept — recall by meaning**: finds "movies about dreams within dreams" even if the word
  "dream" never appears, because meaning is encoded in the vector. You also have a
  **dense-only baseline** (`retrieve_dense`, `_DENSE_SQL`) for comparison/eval.

## 9. Sparse / lexical retrieval (keyword)
- `fts_search` CTE (`app/rag/retriever.py:59`) uses:
  - **`websearch_to_tsquery('english', question)`** — parses the user's text into a tsquery
    (handles quotes, OR, `-` like a search engine).
  - **`@@`** — the match operator (does this chunk's tsvector satisfy the query?).
  - **`ts_rank(...)`** — scores how well it matches, used to order candidates.
- **Concept — precision on exact terms**: catches literal tokens (a specific title/name) where
  embeddings drift.

## 10. Hybrid fusion — Reciprocal Rank Fusion (RRF)
The key architectural idea: run both searches and **combine their rankings**, not their raw scores.
- **Why rank-based, not score-based**: cosine distance and `ts_rank` are on totally different
  scales — you can't add them directly. RRF uses each candidate's **position** in each list instead.
- **The formula** (`app/rag/retriever.py:76`):
  `rrf_score = 1/(60 + rank_vector) + 1/(60 + rank_fts)`
  - A chunk ranking well on *either* side gets some score; ranking well on *both* gets a lot.
  - **`_RRF_K = 60`** (`app/rag/retriever.py:46`) — the standard constant (Cormack et al. 2009);
    damps how much the very top ranks dominate. Nothing to tune.
  - **`FULL OUTER JOIN ... COALESCE(..., 0)`** (`app/rag/retriever.py:79`) — a chunk found by
    only one method still scores (the missing side contributes 0).
- **Candidate pool** — `candidate_pool = k * 4` (`_CANDIDATE_MULTIPLIER`,
  `app/rag/retriever.py:45`). Each side pulls 4× more candidates than the final `k` so fusion
  has room to re-rank before the final cut.
- **Top-k** — final `ORDER BY rrf_score DESC LIMIT k`. Default `k=5` for answers, `k=100` for
  movie rankings.
- **One-SQL design** — both searches + fusion happen in a single statement via CTEs
  (`WITH vector_search`, `fts_search`, `fused`). No app-side merging.
- Two consumers: `retrieve` (returns full chunk text for answering) and
  `retrieve_movie_rankings` (movie IDs + scores only, for hybrid movie search — note
  `MAX(rrf_score) GROUP BY movie_id`, `app/rag/retriever.py:130`).

## 11. Augmentation (build the prompt context)
- `format_context` (`app/rag/generator.py:34`) numbers the retrieved chunks: `[1] ... [2] ...`.
- **Sub-concepts:**
  - **Numbering enables citation** — the system prompt tells the model to cite by title/year,
    and numbering gives it discrete, referenceable sources.
  - **Context window discipline** — only top-k chunks go in, keeping the prompt small and on-topic.

## 12. Generation (grounded answer)
`generate` (`app/rag/generator.py:40`) → Groq (OpenAI-compatible client).
- **Sub-concepts:**
  - **Grounding / anti-hallucination** — the system prompt (`app/rag/generator.py:9`) says
    *answer using ONLY the numbered movies; if context lacks it, say so and stop*. This is what
    makes it RAG and not free-association.
  - **Low temperature** (`0.3`, `app/rag/generator.py:60`) — favors faithful, deterministic
    answers over creativity.
  - **`max_tokens=350`** — bounds answer length.
  - **System vs user roles** — instructions in `system`, context+question in `user`
    (`app/rag/generator.py:56`).
  - **Shared async client** — one `AsyncOpenAI` instance reuses an HTTP/TLS pool across
    requests (`app/rag/generator.py:28`).

---

# Cross-cutting concepts (tie it together)

## 13. Dense vs sparse, and why hybrid
- **Dense (embeddings)**: strong on *meaning/synonyms*, weak on *exact rare tokens*.
- **Sparse (FTS)**: strong on *exact keywords*, blind to *paraphrase*.
- **Hybrid + RRF** gets the union of both strengths — the retriever's whole reason for existing.

## 14. The "no retrain, but yes re-embed" rule
- RAG's payoff: adding knowledge = a cheap **embed** step, **not** retraining the LLM.
- But new/edited movies still need `run_embed.py` to get a vector. `build_chunks_missing`
  (`app/ingest/chunker.py:155`) makes that **incremental** — only embeds movies lacking a
  `full` chunk.

## 15. Evaluation
- **Ragas** (`python -m eval.run`) with **Groq as the LLM judge** measures answer quality
  (faithfulness/grounding, relevance). Concept: RAG quality is measured on *both* retrieval
  (did we fetch the right chunks?) and generation (did the answer stay grounded?).

---

## One-line mental model to memorize

> **Index**: movie → parse → one chunk → 384-d vector (pgvector) + tsvector (FTS).
> **Query**: question → vector + tsquery → two ranked lists → **RRF fuse** → top-k chunks → grounded LLM answer.
