"""
Central factory for LLM model names and embedding model configuration.

All code that needs a model name or an embed model imports from here.
Settings are read from environment variables (loaded by config.py via python-dotenv):

    EMA_LLM_MODEL      — default LLM model name  (fallback: claude-haiku-4-5-20251001)
    EMA_EMBED_MODEL    — default embed model name (fallback: BAAI/bge-large-en-v1.5)
    EMA_EMBED_PROVIDER — embed backend: "huggingface" (default, local) | "openai"
    EMA_HF_CACHE_DIR   — HF weight cache for the embed model
                         (fallback: $EMA_DATA_DIR/models/hf)

Precedence (high → low):
  1. Per-call override argument
  2. EMA_* env var in ~/Nextcloud/Datasets/ema_nlp/ema_nlp.env
  3. Constant defaults below
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from llama_index.core.settings import Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

from config import EMA_DATA_DIR

_log = logging.getLogger(__name__)

_DEFAULT_LLM = "claude-haiku-4-5-20251001"
_DEFAULT_EMBED = "BAAI/bge-large-en-v1.5"
_DEFAULT_PROVIDER = "huggingface"

# Process-wide embed-model cache. A HuggingFaceEmbedding loads a full
# SentenceTransformer onto the GPU (~1.3 GB for bge-large); the Chainlit app
# calls configure_embed_model() on *every* session start/resume *and* every
# retriever build, so without this cache each session leaked 2+ copies onto the
# 3090 until it OOM'd (`torch.OutOfMemoryError`). Keyed by the resolved config so
# all sessions share one instance; a lock serialises creation so a burst of
# concurrent resumes can't race and build several models at once.
_embed_lock = threading.Lock()
_embed_cache: dict[tuple[str, str, str | None, int | None], Any] = {}
_llm_disabled_logged = False


def configure_embed_model(
    model_name: str | None = None,
    *,
    device: str | None = None,
    embed_batch_size: int | None = None,
) -> None:
    """Set LlamaIndex Settings.embed_model. Idempotent + cached.

    The embed model is a process-wide singleton keyed by ``(provider, name,
    device, embed_batch_size)`` — repeated calls with the same config reuse the
    one already loaded instead of allocating another copy on the GPU.

    Args:
        model_name: override the default embed model name.
        device: torch device string ('cuda', 'cuda:0', 'cpu'). Only honoured by
            the huggingface backend. None preserves the prior CPU default.
        embed_batch_size: HuggingFaceEmbedding batch size; defaults to the
            class default (10) when None.
    """
    name = model_name or os.getenv("EMA_EMBED_MODEL", _DEFAULT_EMBED)
    provider = os.getenv("EMA_EMBED_PROVIDER", _DEFAULT_PROVIDER)
    key = (provider, name, device, embed_batch_size)

    with _embed_lock:
        model = _embed_cache.get(key)
        if model is None:
            if provider == "openai":
                from llama_index.embeddings.openai import OpenAIEmbedding  # optional dep

                model = OpenAIEmbedding(model=name)
            else:
                # Weights are cached on disk (default: $EMA_DATA_DIR/models/hf) and
                # only downloaded once; later loads read from this folder. The
                # unauthenticated-HF-Hub warning on load is a revision *check*, not
                # a re-download — set HF_HUB_OFFLINE=1 in ~/Nextcloud/Datasets/ema_nlp/ema_nlp.env to
                # skip it once the weights are cached.
                cache_dir = os.getenv("EMA_HF_CACHE_DIR") or str(EMA_DATA_DIR / "models" / "hf")
                kwargs: dict = {"model_name": name, "cache_folder": cache_dir}
                if device is not None:
                    kwargs["device"] = device
                if embed_batch_size is not None:
                    kwargs["embed_batch_size"] = embed_batch_size
                model = HuggingFaceEmbedding(**kwargs)
            _embed_cache[key] = model

        Settings.embed_model = model
        # Retrieval-only path: no LLM is ever invoked here (kg_extractors=[],
        # vector search + Cypher only). Setting Settings.llm = None makes
        # LlamaIndex print "LLM is explicitly disabled. Using MockLLM." — that
        # message is expected and harmless; agents/judges get their real LLM
        # explicitly via harness.llms, never from Settings.
        global _llm_disabled_logged
        if not _llm_disabled_logged:
            _llm_disabled_logged = True
            _log.info(
                "Settings.llm = None (retrieval-only) — LlamaIndex will report "
                "'LLM is explicitly disabled. Using MockLLM.'; expected, no LLM "
                "runs on the retrieval path."
            )
        Settings.llm = None


def get_llm_model(override: str | None = None) -> str:
    """Return the model name to use: override → EMA_LLM_MODEL env → default."""
    return override or os.getenv("EMA_LLM_MODEL", _DEFAULT_LLM)
