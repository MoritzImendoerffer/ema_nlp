"""
LlamaIndex LLM factory — role-based model selection.

Reads model configuration from harness/configs/models.yaml via
harness.models.load_model_for_role(). Returns a LlamaIndex LLM instance
compatible with llm.chat(), llm.achat(), and all LlamaIndex workflows.

Usage::

    from harness.llms import get_llm

    llm = get_llm("agent")    # → Anthropic(claude-haiku-4-5, ...)
    llm = get_llm("judge")    # → Anthropic(claude-opus-4-7, ...)
    llm = get_llm("grader")   # → Anthropic(claude-haiku-4-5, ...) by default

Available roles (defined in models.yaml):
    agent, grader, rewriter, reranker, judge, reviewer
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from llama_index.core.llms import LLM

from harness.models import load_model_for_role

log = logging.getLogger(__name__)

_TOGETHER_BASE_URL = "https://api.together.xyz/v1"


def get_llm(role_name: str) -> LLM:
    """
    Return a LlamaIndex LLM for the given role.

    Args:
        role_name: Role key defined in models.yaml (e.g. 'agent', 'judge').

    Returns:
        Anthropic LLM for anthropic provider,
        OpenAI (Together AI) for together_ai provider,
        OpenAI (custom api_base) for openai_compatible provider.

    Raises:
        EnvironmentError: If the required API key env var is missing.
        ValueError:       If the role or provider is unrecognised.
    """
    cfg = load_model_for_role(role_name)

    if cfg.provider == "anthropic":
        return _make_anthropic(cfg.model_id, cfg.temperature, cfg.max_tokens)
    elif cfg.provider == "together_ai":
        return _make_together(cfg.model_id, cfg.temperature, cfg.max_tokens)
    elif cfg.provider == "openai_compatible":
        return _make_openai_compatible(
            cfg.model_id, cfg.temperature, cfg.max_tokens,
            api_base=cfg.api_base or "http://localhost:8000/v1",
            api_key_env=cfg.api_key_env or "OPENAI_API_KEY",
        )
    else:
        raise ValueError(
            f"Unknown provider '{cfg.provider}' for role '{role_name}'. "
            "Expected 'anthropic', 'together_ai', or 'openai_compatible'."
        )


def get_llm_for_model(model_name: str, temperature_override: float | None = None) -> LLM:
    """Build a LlamaIndex LLM from a model name key in models.yaml.

    Useful when the caller knows the model name directly rather than a role.

    Args:
        model_name:          Key in the models: section of models.yaml.
        temperature_override: Replaces the temperature from models.yaml if given.

    Raises:
        ValueError:      If model_name is not in models.yaml.
        EnvironmentError: If required API key is missing.
    """
    import yaml

    models_yaml = Path(__file__).parent / "configs" / "models.yaml"
    with models_yaml.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    models: dict = raw.get("models", {})
    if model_name not in models:
        raise ValueError(f"Unknown model '{model_name}'. Available: {sorted(models)}")

    d = models[model_name]
    temp = temperature_override if temperature_override is not None else float(d["temperature"])
    model_id = d["model_id"]
    max_tokens = int(d["max_tokens"])
    provider = d["provider"]

    if provider == "anthropic":
        return _make_anthropic(model_id, temp, max_tokens)
    elif provider == "together_ai":
        return _make_together(model_id, temp, max_tokens)
    elif provider == "openai_compatible":
        return _make_openai_compatible(
            model_id, temp, max_tokens,
            api_base=d.get("api_base", "http://localhost:8000/v1"),
            api_key_env=d.get("api_key_env", "OPENAI_API_KEY"),
        )
    raise ValueError(f"Unknown provider '{provider}' for model '{model_name}'.")


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


def _make_openai_compatible(
    model_id: str,
    temperature: float,
    max_tokens: int,
    *,
    api_base: str,
    api_key_env: str,
) -> LLM:
    try:
        from llama_index.llms.openai import OpenAI
    except ImportError as exc:
        raise ImportError("pip install llama-index-llms-openai") from exc

    api_key = os.getenv(api_key_env, "local")
    if not api_key:
        raise OSError(
            f"{api_key_env} not set. Add it to ~/.myenvs/ema_nlp.env"
        )

    return OpenAI(
        model=model_id,
        api_base=api_base,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
    )
