import asyncio
from types import SimpleNamespace

from app.generate import llm as sync_generator
from app.rag import generator as rag_generator


def _response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def test_rag_generator_uses_groq_model(monkeypatch) -> None:
    request = {}
    assert str(rag_generator._client.base_url) == "https://api.groq.com/openai/v1/"

    class Completions:
        async def create(self, **kwargs):
            request.update(kwargs)
            return _response("grounded answer")

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions())
    )
    monkeypatch.setattr(rag_generator, "_client", client)

    answer = asyncio.run(rag_generator.generate("Which movie?", []))

    assert answer == "grounded answer"
    assert request["model"] == rag_generator.settings.groq_model


def test_sync_generator_uses_groq_model(monkeypatch) -> None:
    request = {}
    assert str(sync_generator._client.base_url) == "https://api.groq.com/openai/v1/"

    class Completions:
        def create(self, **kwargs):
            request.update(kwargs)
            return _response("generated answer")

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions())
    )
    monkeypatch.setattr(sync_generator, "_client", client)

    answer = sync_generator.generate("Recommend a movie")

    assert answer == "generated answer"
    assert request["model"] == sync_generator.settings.groq_model
