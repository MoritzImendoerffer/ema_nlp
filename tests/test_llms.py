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


def test_claude5_metadata_falls_back_when_library_table_is_stale():
    llm = _make_anthropic("claude-sonnet-5", 0.0, 1024)
    meta = llm.metadata  # library lookup raises "Unknown model" -> shim values
    assert meta.context_window == 200_000
    assert meta.is_function_calling_model is True  # "-3"/"-4" check must not disable tools
    assert meta.num_output == 1024


def test_known_model_metadata_untouched():
    llm = _make_anthropic("claude-opus-4-7", 0.0, 2048)
    meta = llm.metadata
    assert meta.is_function_calling_model is True
    assert meta.num_output == 2048
