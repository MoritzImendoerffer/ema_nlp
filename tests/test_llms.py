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


def test_opus_5_5_drops_temperature():
    """claude-opus-5-5 is the judge since 2026-11-23; a real call with temperature got a 400."""
    llm = _make_anthropic("claude-opus-5-5", 0.0, 1024)
    assert "temperature" not in llm._model_kwargs


def test_agent_model_sends_the_workspace_header(monkeypatch):
    """An organization-scoped key got 400 'not scoped to a workspace' without this header."""
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "wrkspc_test")
    llm = _make_anthropic("claude-opus-4-7", 0.0, 1024)
    # The FunctionAgent awaits the async client; check both.
    for client in (llm._client, llm._aclient):
        assert client.default_headers.get("anthropic-workspace-id") == "wrkspc_test"

    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID")
    llm = _make_anthropic("claude-opus-4-7", 0.0, 1024)
    for client in (llm._client, llm._aclient):
        assert "anthropic-workspace-id" not in client.default_headers


_FIRST_DUMP_SCRIPT = r'''
from anthropic._models import construct_type
from anthropic.types import Message
from llama_index.core.base.llms.types import ChatMessage
from llama_index.llms.anthropic.base import AnthropicChatResponse
from mlflow.tracing.utils import dump_span_attribute_value

BODY = {
    "id": "msg_x", "type": "message", "role": "assistant", "model": "claude-opus-4-7",
    "content": [{"type": "tool_use", "id": "toolu_x", "name": "Answer", "input": {"answer": "4"},
                 "caller": {"type": "direct"}}],
    "stop_reason": "tool_use", "stop_sequence": None, "stop_details": None, "container": None,
    "usage": {"input_tokens": 10, "output_tokens": 5, "cache_creation": {
        "ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0},
        "output_tokens_details": {}, "service_tier": "standard"},
}

def dump():
    msg = construct_type(type_=Message, value=BODY)  # as the SDK builds a response
    resp = AnthropicChatResponse(message=ChatMessage(role="assistant", content="4"), raw=dict(msg))
    try:
        dump_span_attribute_value(resp)  # what autolog does when the CHAT_MODEL span ends
        return "OK"
    except TypeError as exc:
        return "FAIL " + str(exc)

print("BEFORE", dump())
from harness.llms import _make_anthropic
_make_anthropic("claude-opus-4-7", 0.0, 64)
print("AFTER", dump())
'''


def test_first_traced_response_serializes():
    """The first claude-opus-4-7 response of a process left an autolog span unended.

    Live evaluation run of 2026-11-23: mlflow's encoder hit an unbuilt SDK class
    ('MockValSer' object is not an instance of 'SchemaSerializer'), the CHAT_MODEL span
    never ended, and the trace was written after the runner read it. Runs in a fresh
    interpreter: in this process other tests may have built the classes already.
    """
    import os
    import subprocess
    import sys

    env = {**os.environ, "ANTHROPIC_API_KEY": "test-key"}
    out = subprocess.run(
        [sys.executable, "-c", _FIRST_DUMP_SCRIPT], capture_output=True, text=True, env=env, timeout=120
    )
    lines = dict(line.split(" ", 1) for line in out.stdout.splitlines() if line[:6] in ("BEFORE", "AFTER "))
    assert "AFTER" in lines, out.stderr[-2000:]
    if lines.get("BEFORE") == "OK":
        pytest.skip("the installed anthropic/pydantic no longer show the defect; the warm-up may be removable")
    assert "MockValSer" in lines["BEFORE"]
    assert lines["AFTER"] == "OK"
