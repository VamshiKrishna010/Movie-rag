"""
Ragas configuration for the movie-RAG eval harness.

  - Judge LLM: Cerebras's llama-3.3-70b via OpenAI-compatible endpoint.
    (langchain-cerebras is stuck on old langchain-core, so we use the
    OpenAI client pointed at Cerebras's URL — same wire protocol.)
  - Embedder:  local bge-small-en-v1.5    (same model as the retriever)
"""

# ─── Workaround for ragas issue #2741 ───────────────────────────────────────
# ragas 0.4.x does a top-level `from langchain_community.chat_models.vertexai
# import ChatVertexAI` — but langchain-community 0.4.x removed that path.
# We don't use VertexAI, so we register a stub module *before* importing ragas.
import sys
import types

try:
    import langchain_community.chat_models.vertexai  # noqa: F401
except ModuleNotFoundError:
    _stub = types.ModuleType("langchain_community.chat_models.vertexai")

    class ChatVertexAI:  # pragma: no cover
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "ChatVertexAI stub — VertexAI is not configured in this project."
            )

    _stub.ChatVertexAI = ChatVertexAI
    sys.modules["langchain_community.chat_models.vertexai"] = _stub
# ─────────────────────────────────────────────────────────────────────────────

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_huggingface import HuggingFaceEmbeddings

from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper

load_dotenv()


# ---- Judge LLM ---------------------------------------------------------------

_cerebras_llm = ChatOpenAI(
    model="gpt-oss-120b",
    api_key=os.environ["CEREBRAS_API_KEY"],
    base_url="https://api.cerebras.ai/v1",
    temperature=0,
)
JUDGE_LLM = LangchainLLMWrapper(_cerebras_llm, bypass_n=True)


# ---- Judge embedder ----------------------------------------------------------
_hf_embedder = HuggingFaceEmbeddings(
    model_name="BAAI/bge-small-en-v1.5",
    encode_kwargs={"normalize_embeddings": True},
)
JUDGE_EMBEDDER = LangchainEmbeddingsWrapper(_hf_embedder)
