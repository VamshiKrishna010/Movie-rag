from typing import List

from openai import AsyncOpenAI

from app.rag.retriever import RetrievedChunk
from app.config import settings


SYSTEM_PROMPT = """You are a movie recommendation assistant. Answer the user's question using ONLY the numbered movies in the context below.

Grounding:
- Use only facts stated in the provided movies. Never add outside knowledge, and never invent titles, years, plots, cast, or ratings.
- If the context lacks the information needed, say so plainly and stop. Do not guess or pad the answer.

Answering:
- Lead with the direct answer or recommendation — no preamble like "Based on the context...".
- Cite movies by their exact title and year. If a year isn't in the context, omit it rather than guessing.
- When recommending, briefly say why each pick fits the request, grounded in its context entry.
- Match the question: recommendations get a short ranked list; factual questions get a direct answer.
- Be concise. Plain prose or a short list, no filler.
"""


# Module-level shared async client. The AsyncOpenAI client maintains an
# HTTP connection pool internally; reusing one instance across requests avoids
# re-establishing TCP/TLS on every call. Groq serves an OpenAI-compatible API,
# so we only need to override base_url.
_client = (
    AsyncOpenAI(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
    )
    if settings.groq_api_key
    else None
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
    if _client is None:
        raise RuntimeError("GROQ_API_KEY must be configured for LLM generation")

    context = format_context(chunks)

    user_message = f"""Context (retrieved movies):
{context}

Question: {question}

Answer:"""

    response = await _client.chat.completions.create(
        model=model or settings.groq_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.3,  # low — we want grounded, not creative
        max_tokens=350,
    )

    if not response.choices:
        raise RuntimeError("Groq chat completion returned no choices")

    content = response.choices[0].message.content
    if content is None:
        raise RuntimeError("Groq chat completion returned empty content")

    return content
