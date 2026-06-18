from typing import List
from app.ingest.store import VectorStore

# module-level store for demos; replace with a real DB-backed store.
_store = VectorStore()


def index_texts(texts: List[str]):
    from app.ingest.embedder import embed_texts

    embeddings = embed_texts(texts)
    _store.add(texts, embeddings)


def retrieve(query: str, k: int = 5) -> List[str]:
    """Return top-k candidate documents for a query (stubbed)."""
    # A real implementation would embed the query and run nearest-neighbor search.
    return _store.query(None, k)
