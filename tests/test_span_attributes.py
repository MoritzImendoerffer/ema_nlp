"""
Tests for WorkflowRunner span-attribute stamping (Changes 1 and 2 of harness refactoring).

Four scenarios:
  1. Recording span — config_attributes() keys stamped before workflow runs.
  2. Non-recording span (Phoenix disabled) — no exception raised.
  3. Workflow without config_attributes() — warning logged, no crash.
  4. retrieve_fn with ablation_config — ablation flags reflected in stamped attributes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from harness.workflows.utils import WorkflowRunner


# ---------------------------------------------------------------------------
# Minimal fake workflow that resolves immediately
# ---------------------------------------------------------------------------

class _MinimalWorkflow:
    """Fake workflow: run() coroutine returns a fixed dict."""

    async def run(self, **kwargs: Any) -> dict:
        return {"answer_text": "ok", "docs": []}

    def config_attributes(self) -> dict:
        return {
            "ema.orchestration.strategy": "simple_rag",
            "ema.orchestration.prompt_strategy": "zero_shot",
            "ema.retrieval.strategy": "flat",
            "ema.retrieval.mode": "dense",
            "ema.retrieval.k": 5,
            "ema.retrieval.reranker": "none",
            "ema.retrieval.query_expansion": False,
            "ema.retrieval.topic_filter": "none",
        }


class _NoAttrsWorkflow:
    """Fake workflow without config_attributes()."""

    async def run(self, **kwargs: Any) -> dict:
        return {"answer_text": "ok", "docs": []}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Test 1: Recording span — attributes stamped
# ---------------------------------------------------------------------------

def test_recording_span_receives_config_attributes():
    mock_span = MagicMock()
    mock_span.is_recording.return_value = True

    runner = WorkflowRunner(_MinimalWorkflow())

    with patch("opentelemetry.trace.get_current_span", return_value=mock_span):
        result = _run(runner.ainvoke({"question": "test", "run_id": "abc-123", "source": "eval"}))

    assert result["answer_text"] == "ok"

    set_calls = {call.args[0]: call.args[1] for call in mock_span.set_attribute.call_args_list}
    assert set_calls["ema.orchestration.strategy"] == "simple_rag"
    assert set_calls["ema.retrieval.mode"] == "dense"
    assert set_calls["ema.retrieval.k"] == 5
    assert set_calls["ema.run.id"] == "abc-123"
    assert set_calls["ema.run.source"] == "eval"


# ---------------------------------------------------------------------------
# Test 2: Non-recording span — silent, no exception
# ---------------------------------------------------------------------------

def test_non_recording_span_is_silent():
    mock_span = MagicMock()
    mock_span.is_recording.return_value = False

    runner = WorkflowRunner(_MinimalWorkflow())

    with patch("opentelemetry.trace.get_current_span", return_value=mock_span):
        result = _run(runner.ainvoke({"question": "test"}))

    assert result["answer_text"] == "ok"
    mock_span.set_attribute.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: Missing config_attributes() — warning logged, no crash
# ---------------------------------------------------------------------------

def test_missing_config_attributes_warns_once(caplog):
    WorkflowRunner._warned_no_config_attrs.clear()

    mock_span = MagicMock()
    mock_span.is_recording.return_value = True

    runner = WorkflowRunner(_NoAttrsWorkflow())

    with patch("opentelemetry.trace.get_current_span", return_value=mock_span):
        with caplog.at_level(logging.WARNING, logger="harness.workflows.utils"):
            result = _run(runner.ainvoke({"question": "test"}))

    assert result["answer_text"] == "ok"
    assert any("no config_attributes" in r.message for r in caplog.records)
    # run_id / source not stamped when method absent
    keys = {call.args[0] for call in mock_span.set_attribute.call_args_list}
    assert "ema.orchestration.strategy" not in keys


# ---------------------------------------------------------------------------
# Test 4: retrieve_fn with ablation_config — ablation flags on span
# ---------------------------------------------------------------------------

def test_ablation_config_reflected_in_span_attributes():
    from harness.retrieve import AblationConfig

    abl = AblationConfig(reranker="sme", query_expansion={"enabled": True})

    class _FakeRetrieveFn:
        ablation_config = abl
        def __call__(self, q):
            return []

    class _WorkflowWithAblation:
        def __init__(self):
            self._prompt_strategy = "zero_shot"
            self._config = type("C", (), {"strategy": "flat", "mode": "hybrid", "k": 10})()
            self._retrieve_fn = _FakeRetrieveFn()

        async def run(self, **kwargs):
            return {"answer_text": "ok", "docs": []}

        def config_attributes(self):
            a = getattr(self._retrieve_fn, "ablation_config", None)
            return {
                "ema.orchestration.strategy": "simple_rag",
                "ema.orchestration.prompt_strategy": self._prompt_strategy,
                "ema.retrieval.strategy": self._config.strategy,
                "ema.retrieval.mode": self._config.mode,
                "ema.retrieval.k": self._config.k,
                "ema.retrieval.reranker": a.reranker or "none" if a else "none",
                "ema.retrieval.query_expansion": a.query_expansion_enabled if a else False,
                "ema.retrieval.topic_filter": a.topic_filter_mode or "none" if a else "none",
            }

    mock_span = MagicMock()
    mock_span.is_recording.return_value = True
    runner = WorkflowRunner(_WorkflowWithAblation())

    with patch("opentelemetry.trace.get_current_span", return_value=mock_span):
        _run(runner.ainvoke({"question": "test"}))

    attrs = {call.args[0]: call.args[1] for call in mock_span.set_attribute.call_args_list}
    assert attrs["ema.retrieval.reranker"] == "sme"
    assert attrs["ema.retrieval.query_expansion"] is True
