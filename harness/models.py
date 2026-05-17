"""
Unified LLM interface for the three model tiers used in Ablation C.

    mid      — claude-haiku-4-5-20251001  (Anthropic, fast/cheap)
    frontier — claude-opus-4-7            (Anthropic, highest quality)
    olmo     — allenai/OLMo-2-1124-32B-Instruct (Together AI, open-weight)

Config is read from harness/configs/models.yaml and can be overridden per-run
via the eval YAML or env vars.

Usage:
    from harness.models import call_model, load_tier, TIER_MID, TIER_FRONTIER, TIER_OLMO
    response = call_model("Explain X", tier_id=TIER_MID)

Smoke test (requires ANTHROPIC_API_KEY; TOGETHER_API_KEY optional for olmo):
    python -m harness.models
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

log = logging.getLogger(__name__)

TIER_MID = "mid"
TIER_FRONTIER = "frontier"
TIER_OLMO = "olmo"

TierId = Literal["mid", "frontier", "olmo"]

_MODELS_YAML = Path(__file__).parent / "configs" / "models.yaml"
_TOGETHER_BASE_URL = "https://api.together.xyz/v1"


@dataclass
class ModelConfig:
    tier_id: str
    description: str
    provider: str          # "anthropic" | "together_ai"
    model_id: str
    max_tokens: int
    temperature: float


def load_tier(tier_id: TierId, config_path: Path = _MODELS_YAML) -> ModelConfig:
    """Load a ModelConfig from models.yaml by tier_id."""
    with config_path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    tiers = raw["tiers"]
    if tier_id not in tiers:
        raise ValueError(f"Unknown tier '{tier_id}'. Available: {list(tiers)}")
    d = tiers[tier_id]
    return ModelConfig(
        tier_id=d["tier_id"],
        description=d["description"],
        provider=d["provider"],
        model_id=d["model_id"],
        max_tokens=d["max_tokens"],
        temperature=d["temperature"],
    )


def call_model(
    prompt: str,
    tier_id: TierId = TIER_MID,  # type: ignore[assignment]
    system: str = "",
    *,
    config: ModelConfig | None = None,
    model_id_override: str | None = None,
) -> str:
    """
    Call the LLM for the given tier and return the response text.

    Args:
        prompt:           User-turn content.
        tier_id:          Which tier to use (ignored if ``config`` is provided).
        system:           Optional system prompt.
        config:           Pre-loaded ModelConfig; overrides tier_id if given.
        model_id_override: Override the model_id from the config (for one-off calls).

    Returns:
        Response text string.

    Raises:
        EnvironmentError: If the required API key is missing.
        ImportError:      If the required SDK is not installed.
    """
    cfg = config or load_tier(tier_id)
    model_id = model_id_override or cfg.model_id

    if cfg.provider == "anthropic":
        return _call_anthropic(prompt, system, model_id, cfg.max_tokens, cfg.temperature)
    elif cfg.provider == "together_ai":
        return _call_together(prompt, system, model_id, cfg.max_tokens, cfg.temperature)
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
        raise OSError(
            "ANTHROPIC_API_KEY not set. Add it to ~/.myenvs/ema_nlp.env"
        )

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


def _call_together(
    prompt: str,
    system: str,
    model_id: str,
    max_tokens: int,
    temperature: float,
) -> str:
    try:
        from openai import OpenAI
    except ImportError as e:
        raise ImportError("pip install openai") from e

    api_key = os.getenv("TOGETHER_API_KEY")
    if not api_key:
        raise OSError(
            "TOGETHER_API_KEY not set. Add it to ~/.myenvs/ema_nlp.env. "
            "Get a key at https://api.together.xyz"
        )

    client = OpenAI(api_key=api_key, base_url=_TOGETHER_BASE_URL)
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

    tiers_to_test: list[TierId] = [TIER_MID, TIER_FRONTIER]  # type: ignore[list-item]
    if os.getenv("TOGETHER_API_KEY"):
        tiers_to_test.append(TIER_OLMO)  # type: ignore[arg-type]
    else:
        log.warning("TOGETHER_API_KEY not set — skipping OLMo smoke test")

    prompt = "Reply with exactly: 'model check OK'"
    all_ok = True
    for tier_id in tiers_to_test:
        cfg = load_tier(tier_id)
        try:
            response = call_model(prompt, config=cfg)
            log.info("[%s] %s → %r", tier_id, cfg.model_id, response[:80])
        except OSError as exc:
            log.error("[%s] missing credentials: %s", tier_id, exc)
            all_ok = False
        except Exception as exc:
            log.error("[%s] call failed: %s", tier_id, exc)
            all_ok = False

    sys.exit(0 if all_ok else 1)
