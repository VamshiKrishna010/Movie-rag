# Implement MRR@K Evaluation

## Summary

Add a standalone retrieval evaluator because MRR measures ranked retrieval, not generation quality. It will call the production retriever directly, avoiding `/query` authentication, LLM generation, and Ragas costs.

MRR will follow the standard definition: each query scores `1 / rank` for its first relevant result, or `0` when none appears within `K`; MRR is the mean across queries. [Reference definition](https://nlp.stanford.edu/IR-book/html/htmledition/evaluation-of-ranked-retrieval-results-1.html).

## Implementation

1. Add pure metric helpers under `eval/metrics.py`:

   - `normalize_title()` using Unicode NFKC normalization, collapsed whitespace, and `casefold()`.
   - `reciprocal_rank_at_k(retrieved_titles, relevant_titles, k)` returning matched title, one-based rank, and reciprocal rank.
   - Match normalized titles exactly—never by substring, so `Dune` does not match `Dune: Part Two`.
   - Use only the earliest relevant result when multiple movies are relevant.
   - Validate `k > 0`; treat no hit as `rank=None`, score `0.0`.

2. Add `eval/mrr.py` with this CLI:

   ```powershell
   app\.venv\Scripts\python.exe -m eval.mrr --strategy hybrid --k 5
   ```

   - Default to `hybrid` and `k=5`.
   - Support `--strategy hybrid|dense|sparse`, mapped to hybrid, dense-only, and keyword/FTS-only retrieval.
   - Load questions and `ground_truth_movies` from [dataset.json](D:/Git_projects/movie-rag/eval/dataset.json:3).
   - Process queries sequentially and fail clearly on retrieval or malformed-label errors instead of recording artificial zeroes.
   - Print per-category MRR@K and overall MRR@K.
   - Write:
     - `eval/results/mrr_<strategy>_<timestamp>.csv`
     - `eval/results/mrr_<strategy>_latest.csv`
   - Include `id`, category, question, strategy, K, relevant movies, retrieved movie IDs/titles/scores, matched movie, first relevant rank, and reciprocal rank.

3. Update the README evaluation section to document the fast MRR command separately from the existing end-to-end Ragas runner in [README.md](D:/Git_projects/movie-rag/README.md:209). Explicitly distinguish evaluation MRR from the production retriever’s Reciprocal Rank Fusion score.

## Tests and Verification

- Add unit tests covering rank 1, later rank, no hit, cutoff exclusion, multiple relevant movies, normalization, exact-versus-substring matching, and aggregate mean.
- Mock both retriever strategies to verify strategy selection, result ordering, and CSV fields without requiring PostgreSQL.
- Run:

  ```powershell
  app\.venv\Scripts\python.exe -m pytest tests/test_eval_metrics.py
  app\.venv\Scripts\python.exe -m eval.mrr --strategy hybrid --k 10
  app\.venv\Scripts\python.exe -m eval.mrr --strategy dense --k 10
  app\.venv\Scripts\python.exe -m eval.mrr --strategy sparse --k 10
```

The evaluator uses four concurrent retrieval workers by default. Pass
`--workers 1` to run sequentially or choose another positive worker count.

- Confirm the reported overall MRR equals the arithmetic mean of the CSV `reciprocal_rank` column.

## Assumptions and Guards

- `ground_truth_movies` remains the relevance source; no dataset migration to movie IDs in this version.
- MRR uses exact normalized titles because the dataset currently supplies titles rather than IDs.
- Production retrieval, `/query`, Ragas evaluation, and existing result files remain unchanged.
- Do not average ranks of every relevant movie, reuse `rrf_score` as MRR, or suppress retrieval failures as zero scores.
