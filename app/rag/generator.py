from typing import List

from openai import AsyncOpenAI

from app.rag.retriever import RetrievedChunk
from app.config import settings


SYSTEM_PROMPT = """You are a movie recommendation assistant. Answer the user's question using ONLY the movie information provided in the context below.

Rules:
- Base your answer strictly on the provided movies. Do not use outside knowledge.
- If the context doesn't contain enough information to answer, say so honestly.
- When recommending or referencing movies, mention them by title and year.
- Be concise. No preamble like "Based on the context...". Just answer.
"""


# Module-level shared async client. The AsyncOpenAI client maintains an
# HTTP connection pool internally; reusing one instance across requests avoids
# re-establishing TCP/TLS on every call. Cerebras serves an OpenAI-compatible
# API, so we just override base_url.
_client = AsyncOpenAI(
    api_key=settings.cerebras_api_key,
    base_url="https://api.cerebras.ai/v1",
)


def format_context(chunks: List[RetrievedChunk]) -> str:
    """Turn retrieved chunks into a numbered context block for the prompt."""
    lines = [f"[{i}] {c.chunk_text}" for i, c in enumerate(chunks, start=1)]
    return "\n\n".join(lines)


async def generate(
    question: str,
    chunks: List[RetrievedChunk],
    model: str | None = None,
) -> str:
    context = format_context(chunks)

    user_message = f"""Context (retrieved movies):
{context}

Question: {question}

Answer:"""

    response = await _client.chat.completions.create(
        model=model or settings.cerebras_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.3,  # low — we want grounded, not creative
        max_tokens=350,
    )

    if not response.choices:
        raise RuntimeError("Cerebras chat completion returned no choices")

    content = response.choices[0].message.content
    if content is None:
        raise RuntimeError("Cerebras chat completion returned empty content")

    return content
