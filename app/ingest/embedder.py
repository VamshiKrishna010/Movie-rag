import asyncio
from functools import lru_cache

from sentence_transformers import SentenceTransformer

MODEL_NAME = "BAAI/bge-small-en-v1.5"
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    """Lazy-load the embedding model (downloads ~130MB on first run, then cached)."""
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_texts(texts: list[str], batch_size: int = 64) -> list[list[float]]:
    """Embed a list of texts. Returns one 384-dim vector per text."""
    if not texts:
        return []
    model = get_model()
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return embeddings.tolist()


def format_vector(vec: list[float]) -> str:
    """Serialize a vector for Postgres ::vector casts (eval / legacy paths)."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


@lru_cache(maxsize=512)
def _embed_query_cached(prefixed: str) -> tuple[float, ...]:
    """CPU-bound embed; tuple is hashable for lru_cache."""
    model = get_model()
    embedding = model.encode(
        prefixed,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return tuple(float(x) for x in embedding)


def embed_query(text: str) -> list[float]:
    """Embed a single query string. bge models want a prefix for queries."""
    prefixed = _QUERY_PREFIX + text
    return list(_embed_query_cached(prefixed))


async def embed_query_async(text: str) -> list[float]:
    """Non-blocking embed — keeps the event loop free under concurrent requests."""
    prefixed = _QUERY_PREFIX + text
    return list(await asyncio.to_thread(_embed_query_cached, prefixed))
