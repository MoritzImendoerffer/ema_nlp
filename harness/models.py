"""
Unified model configuration for EMA NLP harness.

Models and roles are defined in harness/configs/models.yaml:

    models:  {claude_haiku, claude_opus, olmo_32b, local_qwen32}
    roles:   {agent, grader, rewriter, reranker, judge, reviewer}

Usage:
    from harness.models import load_model_for_role, call_model
    cfg  = load_model_for_role("agent")   # → claude_haiku config
    text = call_model("Explain X", "agent")

Smoke test (requires ANTHROPIC_API_KEY):
    python -m harness.models
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger(__name__)

_MODELS_YAML = Path(__file__).parent / "configs" / "models.yaml"
_TOGETHER_BASE_URL = "https://api.together.xyz/v1"


@dataclass
class ModelConfig:
    model_name: str         # key in models: dict
    description: str
    provider: str           # "anthropic" | "together_ai" | "openai_compatible"
    model_id: str
    max_tokens: int
    temperature: float
    api_base: Optional[str] = field(default=None)      # openai_compatible only
    api_key_env: Optional[str] = field(default=None)   # openai_compatible only


def load_model_for_role(role_name: str, config_path: Path = _MODELS_YAML) -> ModelConfig:
    """Load ModelConfig for a given role name.

    Args:
        role_name:   Role key defined in models.yaml (e.g. 'agent', 'judge').
        config_path: Override path to models.yaml.

    Raises:
        ValueError: If role or model name is not found.
    """
    with config_path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    roles: dict = raw.get("roles", {})
    if role_name not in roles:
        raise ValueError(
            f"Unknown role '{role_name}'. Available roles: {sorted(roles)}"
        )

    model_name: str = roles[role_name]
    models: dict = raw.get("models", {})
    if model_name not in models:
        raise ValueError(
            f"Role '{role_name}' maps to unknown model '{model_name}'. "
            f"Available models: {sorted(models)}"
        )

    d = models[model_name]
    return ModelConfig(
        model_name=model_name,
        description=d.get("description", ""),
        provider=d["provider"],
        model_id=d["model_id"],
        max_tokens=d["max_tokens"],
        temperature=d["temperature"],
        api_base=d.get("api_base"),
        api_key_env=d.get("api_key_env"),
    )


def call_model(
    prompt: str,
    role_name: str = "agent",
    system: str = "",
    *,
    config: ModelConfig | None = None,
    model_id_override: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """
    Call the LLM for the given role and return the response text.

    Args:
        prompt:           User-turn content.
        role_name:        Which role to use (resolved via models.yaml roles:).
        system:           Optional system prompt.
        config:           Pre-loaded ModelConfig; overrides role_name if given.
        model_id_override: Override the model_id (for one-off calls).
        max_tokens:       Override max_tokens from the ModelConfig.

    Returns:
        Response text string.

    Raises:
        EnvironmentError: If the required API key is missing.
        ImportError:      If the required SDK is not installed.
    """
    cfg = config or load_model_for_role(role_name)
    model_id = model_id_override or cfg.model_id
    effective_max_tokens = max_tokens if max_tokens is not None else cfg.max_tokens

    if cfg.provider == "anthropic":
        return _call_anthropic(prompt, system, model_id, effective_max_tokens, cfg.temperature)
    elif cfg.provider == "together_ai":
        return _call_openai_compat(
            prompt, system, model_id, effective_max_tokens, cfg.temperature,
            api_base=_TOGETHER_BASE_URL,
            api_key=os.getenv("TOGETHER_API_KEY"),
            key_env="TOGETHER_API_KEY",
        )
    elif cfg.provider == "openai_compatible":
        key_env = cfg.api_key_env or "OPENAI_API_KEY"
        return _call_openai_compat(
            prompt, system, model_id, effective_max_tokens, cfg.temperature,
            api_base=cfg.api_base or "http://localhost:8000/v1",
            api_key=os.getenv(key_env),
            key_env=key_env,
        )
    else:
        raise ValueError(f"Unknown provider '{cfg.provider}'")


# ---------------------------------------------------------------------------
# Provider backends
# ---------------------------------------------------------------------------

def _call_anthropic(
    prompt: str,
    system: str,
    model_id: str,
    max_tokens: int,
    temperature: float,
) -> str:
    try:
        import anthropic
    except ImportError as e:
        raise ImportError("pip install anthropic") from e

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise OSError("ANTHROPIC_API_KEY not set. Add it to ~/.myenvs/ema_nlp.env")

    client = anthropic.Anthropic(api_key=api_key)
    kwargs: dict = dict(
        model=model_id,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    if system:
        kwargs["system"] = system

    msg = client.messages.create(**kwargs)
    return msg.content[0].text


def _call_openai_compat(
    prompt: str,
    system: str,
    model_id: str,
    max_tokens: int,
    temperature: float,
    *,
    api_base: str,
    api_key: str | None,
    key_env: str,
) -> str:
    try:
        from openai import OpenAI
    except ImportError as e:
        raise ImportError("pip install openai") from e

    if not api_key:
        raise OSError(
            f"{key_env} not set. Add it to ~/.myenvs/ema_nlp.env"
        )

    client = OpenAI(api_key=api_key, base_url=api_base)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = client.chat.completions.create(
        model=model_id,
        messages=messages,  # type: ignore[arg-type]
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    roles_to_test = ["agent"]
    if os.getenv("TOGETHER_API_KEY"):
        pass  # add olmo test via config override if needed

    prompt = "Reply with exactly: 'model check OK'"
    all_ok = True
    for role in roles_to_test:
        cfg = load_model_for_role(role)
        try:
            response = call_model(prompt, role)
            log.info("[%s → %s] %r", role, cfg.model_id, response[:80])
        except OSError as exc:
            log.error("[%s] missing credentials: %s", role, exc)
            all_ok = False
        except Exception as exc:
            log.error("[%s] call failed: %s", role, exc)
            all_ok = False

    sys.exit(0 if all_ok else 1)
