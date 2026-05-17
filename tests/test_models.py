"""Tests for harness/models.py (TASK-032)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from harness.models import (
    TIER_FRONTIER,
    TIER_MID,
    TIER_OLMO,
    ModelConfig,
    call_model,
    load_tier,
)


# ---------------------------------------------------------------------------
# load_tier
# ---------------------------------------------------------------------------

def test_load_all_tiers():
    for tier_id in [TIER_MID, TIER_FRONTIER, TIER_OLMO]:
        cfg = load_tier(tier_id)
        assert cfg.tier_id == tier_id
        assert cfg.model_id
        assert cfg.provider in ("anthropic", "together_ai")
        assert cfg.max_tokens > 0


def test_load_tier_unknown_raises():
    with pytest.raises(ValueError, match="Unknown tier"):
        load_tier("unknown_tier")  # type: ignore[arg-type]


def test_mid_tier_is_haiku():
    cfg = load_tier(TIER_MID)
    assert "haiku" in cfg.model_id.lower()
    assert cfg.provider == "anthropic"


def test_frontier_tier_is_opus():
    cfg = load_tier(TIER_FRONTIER)
    assert "opus" in cfg.model_id.lower()
    assert cfg.provider == "anthropic"


def test_olmo_tier_is_together():
    cfg = load_tier(TIER_OLMO)
    assert cfg.provider == "together_ai"
    assert "olmo" in cfg.model_id.lower() or "OLMo" in cfg.model_id


# ---------------------------------------------------------------------------
# call_model — Anthropic path (mocked)
# ---------------------------------------------------------------------------

def test_call_model_anthropic_mid(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    fake_content = MagicMock()
    fake_content.text = "response text"
    fake_msg = MagicMock()
    fake_msg.content = [fake_content]

    with patch("anthropic.Anthropic") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = fake_msg
        mock_client_cls.return_value = mock_client

        result = call_model("Hello", tier_id=TIER_MID)

    assert result == "response text"
    mock_client.messages.create.assert_called_once()


def test_call_model_anthropic_missing_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(OSError, match="ANTHROPIC_API_KEY"):
        call_model("Hello", tier_id=TIER_MID)


def test_call_model_anthropic_with_system(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    fake_content = MagicMock()
    fake_content.text = "ok"
    fake_msg = MagicMock()
    fake_msg.content = [fake_content]

    with patch("anthropic.Anthropic") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = fake_msg
        mock_client_cls.return_value = mock_client

        call_model("Hello", tier_id=TIER_MID, system="You are a helpful assistant.")
        call_kwargs = mock_client.messages.create.call_args[1]
        assert "system" in call_kwargs


# ---------------------------------------------------------------------------
# call_model — Together AI / OLMo path (mocked)
# ---------------------------------------------------------------------------

def test_call_model_together_missing_key(monkeypatch):
    monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
    with pytest.raises(OSError, match="TOGETHER_API_KEY"):
        call_model("Hello", tier_id=TIER_OLMO)


def test_call_model_together_olmo(monkeypatch):
    monkeypatch.setenv("TOGETHER_API_KEY", "test-together-key")
    fake_msg = MagicMock()
    fake_msg.choices[0].message.content = "olmo response"

    with patch("openai.OpenAI") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = fake_msg
        mock_client_cls.return_value = mock_client

        result = call_model("Hello", tier_id=TIER_OLMO)

    assert result == "olmo response"
    _, kwargs = mock_client_cls.call_args
    assert "together.xyz" in kwargs.get("base_url", "")


# ---------------------------------------------------------------------------
# config override
# ---------------------------------------------------------------------------

def test_model_id_override(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    fake_content = MagicMock()
    fake_content.text = "ok"
    fake_msg = MagicMock()
    fake_msg.content = [fake_content]

    with patch("anthropic.Anthropic") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = fake_msg
        mock_client_cls.return_value = mock_client

        call_model("Hi", tier_id=TIER_MID, model_id_override="claude-sonnet-4-6")
        create_kwargs = mock_client.messages.create.call_args[1]
        assert create_kwargs["model"] == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# models.yaml schema
# ---------------------------------------------------------------------------

def test_models_yaml_has_all_tiers():
    yaml_path = Path(__file__).parent.parent / "harness" / "configs" / "models.yaml"
    data = yaml.safe_load(yaml_path.read_text())
    assert set(data["tiers"].keys()) >= {TIER_MID, TIER_FRONTIER, TIER_OLMO}
    for tier in data["tiers"].values():
        assert "model_id" in tier
        assert "provider" in tier
        assert "max_tokens" in tier
