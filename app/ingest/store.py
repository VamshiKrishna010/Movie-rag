import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector_async

from app.config import settings
from app.ingest.chunker import CHUNK_TYPES, build_chunks, build_chunks_missing
from app.ingest.embedder import embed_texts

EMBED_BATCH = 1024   # movies per embed + COPY wave
ENCODE_BATCH = 256   # sentence-transformers internal batch size


async def embed_and_store(
    *,
    full_rebuild: bool = False,
    refresh_types: tuple[str, ...] = (),
    embed_batch: int = EMBED_BATCH,
) -> int:
    """Chunk movies, embed, and store vectors.

    Args:
        full_rebuild: If True, delete all chunks and rebuild from scratch.
                      If False (default), only process movies missing chunks.
        refresh_types: Delete and rebuild only these chunk types before the
                       missing-chunk pass. Use for changed chunk text logic.
        embed_batch:  How many movies to embed per wave (memory vs speed).
    """
    _validate_rebuild_args(full_rebuild=full_rebuild, refresh_types=refresh_types)

    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        await register_vector_async(conn)

        if full_rebuild:
            print("Full rebuild: deleting existing chunks...")
            await conn.execute("DELETE FROM chunks")
            await conn.commit()
            pending = await build_chunks(conn)
        else:
            if refresh_types:
                names = ", ".join(refresh_types)
                print(f"Refreshing chunk types: {names}")
                await conn.execute(
                    "DELETE FROM chunks WHERE chunk_type = ANY(%s)",
                    (list(refresh_types),),
                )
                await conn.commit()
            pending = await build_chunks_missing(conn)

        if not pending:
            total = await _count_chunks(conn)
            print(f"No movies need embedding. {total} chunks already in DB.")
            return 0

        print(f"Embedding {len(pending)} movies in batches of {embed_batch}...")
        stored = 0

        for i in range(0, len(pending), embed_batch):
            batch = pending[i : i + embed_batch]
            texts = [chunk.content for chunk in batch]
            vectors = embed_texts(texts, batch_size=ENCODE_BATCH)
            rows = [
                (chunk.movie_id, chunk.chunk_type, chunk.content, Vector(vector))
                for chunk, vector in zip(batch, vectors)
            ]
            async with conn.cursor() as cur:
                async with cur.copy(
                    "COPY chunks (movie_id, chunk_type, content, embedding) FROM STDIN"
                ) as copy:
                    for row in rows:
                        await copy.write_row(row)
            await conn.commit()
            stored += len(batch)
            print(f"  stored {stored}/{len(pending)} chunks")

        total = await _count_chunks(conn)
        print(f"Done. {stored} new chunks stored ({total} total in DB).")
        return stored


def _validate_rebuild_args(*, full_rebuild: bool, refresh_types: tuple[str, ...]) -> None:
    if full_rebuild and refresh_types:
        raise ValueError("--full-rebuild cannot be combined with --refresh-types")

    invalid = sorted(set(refresh_types) - set(CHUNK_TYPES))
    if invalid:
        valid = ", ".join(CHUNK_TYPES)
        bad = ", ".join(invalid)
        raise ValueError(f"Unknown chunk type(s): {bad}. Valid values: {valid}")


async def _count_chunks(conn: psycopg.AsyncConnection) -> int:
    row = await conn.execute("SELECT COUNT(*) FROM chunks")
    result = await row.fetchone()
    return int(result[0]) if result else 0
