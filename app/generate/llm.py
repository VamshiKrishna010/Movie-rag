from openai import OpenAI

from app.config import settings


_client = (
    OpenAI(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
    )
    if settings.groq_api_key
    else None
)


def generate(prompt: str, model: str | None = None) -> str:
    """Generate a response through Groq's OpenAI-compatible API."""
    if _client is None:
        raise RuntimeError("GROQ_API_KEY must be configured for LLM generation")

    response = _client.chat.completions.create(
        model=model or settings.groq_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=350,
    )

    if not response.choices:
        raise RuntimeError("Groq chat completion returned no choices")

    content = response.choices[0].message.content
    if content is None:
        raise RuntimeError("Groq chat completion returned empty content")

    return content
