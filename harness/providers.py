"""
Central factory for LLM model names and embedding model configuration.

All code that needs a model name or an embed model imports from here.
Settings are read from environment variables (loaded by config.py via python-dotenv):

    EMA_LLM_MODEL      — default LLM model name  (fallback: claude-haiku-4-5-20251001)
    EMA_EMBED_MODEL    — default embed model name (fallback: BAAI/bge-large-en-v1.5)
    EMA_EMBED_PROVIDER — embed backend: "huggingface" (default, local) | "openai"

Precedence (high → low):
  1. Per-call override argument
  2. EMA_* env var in ~/.myenvs/ema_nlp.env
  3. Constant defaults below
"""

from __future__ import annotations

import os

from llama_index.core.settings import Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

_DEFAULT_LLM = "claude-haiku-4-5-20251001"
_DEFAULT_EMBED = "BAAI/bge-large-en-v1.5"
_DEFAULT_PROVIDER = "huggingface"


def configure_embed_model(model_name: str | None = None) -> None:
    """Set LlamaIndex Settings.embed_model. Call once at startup."""
    name = model_name or os.getenv("EMA_EMBED_MODEL", _DEFAULT_EMBED)
    provider = os.getenv("EMA_EMBED_PROVIDER", _DEFAULT_PROVIDER)

    if provider == "openai":
        from llama_index.embeddings.openai import OpenAIEmbedding  # optional dep

        Settings.embed_model = OpenAIEmbedding(model=name)
    else:
        Settings.embed_model = HuggingFaceEmbedding(model_name=name)

    Settings.llm = None  # retrieval-only; no LLM node needed


def get_llm_model(override: str | None = None) -> str:
    """Return the model name to use: override → EMA_LLM_MODEL env → default."""
    return override or os.getenv("EMA_LLM_MODEL", _DEFAULT_LLM)
