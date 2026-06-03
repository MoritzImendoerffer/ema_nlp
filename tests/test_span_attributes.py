"""
Tests for WorkflowRunner span-attribute stamping (Changes 1 and 2 of harness refactoring).

Four scenarios:
  1. Recording span — config_attributes() keys stamped before workflow runs.
  2. Non-recording span (Phoenix disabled) — no exception raised.
  3. Workflow without config_attributes() — warning logged, no crash.
  4. Live OTel SDK — attributes (incl. ema.index.profile) land on the wrapper span.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import MagicMock, patch

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
    # Use a fresh loop instead of asyncio.get_event_loop() — the latter is
    # deprecated on 3.10+ and raises when other tests have closed the
    # default loop (test order dependency).
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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
# Test 4 (NARR-023 regression): live OTel SDK path — attributes must land on
# the runner's wrapper span, not a no-op span. Catches the bug where stamping
# happened before any workflow span existed.
# ---------------------------------------------------------------------------

def test_live_otel_sdk_records_attributes_on_wrapper_span(monkeypatch):
    """End-to-end with a real OTel TracerProvider + in-memory exporter."""
    import opentelemetry.trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    monkeypatch.setattr(otel_trace, "_TRACER_PROVIDER", None, raising=False)
    monkeypatch.setattr(otel_trace, "_TRACER_PROVIDER_SET_ONCE", None, raising=False)
    monkeypatch.setattr(otel_trace, "get_tracer_provider", lambda: provider)
    monkeypatch.setenv("EMA_INDEX_PROFILE", "neo4j_hier")

    runner = WorkflowRunner(_MinimalWorkflow())
    result = _run(runner.ainvoke({"question": "q", "run_id": "rid", "source": "eval"}))
    assert result["answer_text"] == "ok"
    provider.force_flush()

    spans = exporter.get_finished_spans()
    wrapper = [s for s in spans if s.name == "_MinimalWorkflow.invoke"]
    assert wrapper, f"expected a wrapper span, got: {[s.name for s in spans]}"
    attrs = dict(wrapper[0].attributes)
    assert attrs.get("ema.index.profile") == "neo4j_hier"
    assert attrs.get("ema.run.id") == "rid"
    assert attrs.get("ema.run.source") == "eval"
    assert attrs.get("ema.orchestration.strategy") == "simple_rag"
    assert attrs.get("ema.retrieval.mode") == "dense"
