"""Unit tests for harness.llms provider construction (offline — no API calls)."""

from __future__ import annotations

import pytest

from harness.llms import _make_anthropic


@pytest.fixture(autouse=True)
def _fake_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def test_claude5_models_drop_deprecated_temperature():
    # The Claude 5 family 400s on any `temperature`; the wrapper must not send it.
    llm = _make_anthropic("claude-sonnet-5", 0.0, 1024)
    assert "temperature" not in llm._model_kwargs
    assert llm._model_kwargs["max_tokens"] == 1024


def test_older_models_keep_temperature():
    llm = _make_anthropic("claude-haiku-4-5-20251001", 0.0, 1024)
    # prefix match, not substring: the "4-5" in haiku's id must not trigger the strip
    assert llm._model_kwargs["temperature"] == 0.0
