"""
LlamaIndex LLM factory for the three model tiers defined in models.yaml.

Reads model IDs, temperature, and max_tokens from harness/configs/models.yaml
via harness.models.load_tier() — the same source of truth used by call_model().

Usage::

    from harness.llms import get_llm

    llm = get_llm("frontier")   # Anthropic(claude-opus-4-7, ...)
    llm = get_llm("mid")        # Anthropic(claude-haiku-4-5, ...)
    llm = get_llm("olmo")       # OpenAI(OLMo-2-32B via Together AI)

The returned objects are LlamaIndex LLM instances compatible with
llm.chat(), llm.achat(), and LlamaIndex agents/workflows.
"""

from __future__ import annotations

import logging
import os

from llama_index.core.llms import LLM

from harness.models import TierId, load_tier

log = logging.getLogger(__name__)

_TOGETHER_BASE_URL = "https://api.together.xyz/v1"


def get_llm(tier_id: TierId) -> LLM:
    """
    Return a LlamaIndex LLM for the given tier_id.

    Args:
        tier_id: "mid" | "frontier" | "olmo"

    Returns:
        Anthropic LLM for Anthropic tiers, OpenAI (Together AI) for olmo.

    Raises:
        EnvironmentError: If the required API key env var is missing.
        ValueError:       If the provider in models.yaml is unrecognised.
    """
    cfg = load_tier(tier_id)

    if cfg.provider == "anthropic":
        return _make_anthropic(cfg.model_id, cfg.temperature, cfg.max_tokens)
    elif cfg.provider == "together_ai":
        return _make_together(cfg.model_id, cfg.temperature, cfg.max_tokens)
    else:
        raise ValueError(
            f"Unknown provider '{cfg.provider}' for tier '{tier_id}'. "
            "Expected 'anthropic' or 'together_ai'."
        )


def _make_anthropic(model_id: str, temperature: float, max_tokens: int) -> LLM:
    try:
        from llama_index.llms.anthropic import Anthropic
    except ImportError as exc:
        raise ImportError("pip install llama-index-llms-anthropic") from exc

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise OSError("ANTHROPIC_API_KEY not set. Add it to ~/.myenvs/ema_nlp.env")

    return Anthropic(
        model=model_id,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,
    )


def _make_together(model_id: str, temperature: float, max_tokens: int) -> LLM:
    try:
        from llama_index.llms.openai import OpenAI
    except ImportError as exc:
        raise ImportError("pip install llama-index-llms-openai") from exc

    api_key = os.getenv("TOGETHER_API_KEY")
    if not api_key:
        raise OSError(
            "TOGETHER_API_KEY not set. Add it to ~/.myenvs/ema_nlp.env. "
            "Get a key at https://api.together.xyz"
        )

    return OpenAI(
        model=model_id,
        api_base=_TOGETHER_BASE_URL,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
    )
