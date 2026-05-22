"""
LangChain ChatModel factory for the three model tiers defined in models.yaml.

Reads model IDs, temperature, and max_tokens from harness/configs/models.yaml
via harness.models.load_tier() — the same source of truth used by call_model().

Usage::

    from harness.chains.llms import get_langchain_llm

    llm = get_langchain_llm("frontier")   # ChatAnthropic(claude-opus-4-7, ...)
    llm = get_langchain_llm("mid")        # ChatAnthropic(claude-haiku-4-5, ...)
    llm = get_langchain_llm("olmo")       # ChatOpenAI(OLMo-2-32B via Together AI)

The returned objects are standard LangChain BaseChatModel instances and can
be used directly in LCEL chains (llm.invoke, llm.stream, llm.bind_tools, etc.)
or as the LLM node in a LangGraph StateGraph.
"""

from __future__ import annotations

import logging
import os

from langchain_core.language_models.chat_models import BaseChatModel

from harness.models import TierId, load_tier

log = logging.getLogger(__name__)

_TOGETHER_BASE_URL = "https://api.together.xyz/v1"


def get_langchain_llm(tier_id: TierId) -> BaseChatModel:
    """
    Return a LangChain ChatModel for the given tier_id.

    Args:
        tier_id: "mid" | "frontier" | "olmo"

    Returns:
        ChatAnthropic for Anthropic tiers, ChatOpenAI for Together AI.

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


# ---------------------------------------------------------------------------
# Provider backends
# ---------------------------------------------------------------------------

def _make_anthropic(model_id: str, temperature: float, max_tokens: int) -> BaseChatModel:
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as exc:
        raise ImportError("pip install langchain-anthropic") from exc

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise OSError("ANTHROPIC_API_KEY not set. Add it to ~/.myenvs/ema_nlp.env")

    return ChatAnthropic(
        model=model_id,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,  # type: ignore[arg-type]
    )


def _make_together(model_id: str, temperature: float, max_tokens: int) -> BaseChatModel:
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise ImportError("pip install langchain-openai") from exc

    api_key = os.getenv("TOGETHER_API_KEY")
    if not api_key:
        raise OSError(
            "TOGETHER_API_KEY not set. Add it to ~/.myenvs/ema_nlp.env. "
            "Get a key at https://api.together.xyz"
        )

    return ChatOpenAI(
        model=model_id,
        base_url=_TOGETHER_BASE_URL,
        api_key=api_key,  # type: ignore[arg-type]
        temperature=temperature,
        max_tokens=max_tokens,
    )
