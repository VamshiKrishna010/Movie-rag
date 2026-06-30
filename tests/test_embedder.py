from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import time

from app.ingest import embedder


def test_get_model_initializes_once_under_concurrent_first_use(monkeypatch) -> None:
    constructor_calls = 0
    call_lock = Lock()
    fake_model = object()

    def fake_sentence_transformer(_model_name: str):
        nonlocal constructor_calls
        with call_lock:
            constructor_calls += 1
        time.sleep(0.02)
        return fake_model

    monkeypatch.setattr(embedder, "_model", None)
    monkeypatch.setattr(embedder, "SentenceTransformer", fake_sentence_transformer)

    with ThreadPoolExecutor(max_workers=4) as executor:
        models = list(executor.map(lambda _: embedder.get_model(), range(4)))

    assert constructor_calls == 1
    assert models == [fake_model] * 4
