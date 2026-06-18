import asyncio
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

os.environ.setdefault("DATABASE_URL", "postgresql://rag:rag@localhost:5432/movierag")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("TMDB_API_KEY", "test")
os.environ.setdefault("CEREBRAS_API_KEY", "test")

from app.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client
