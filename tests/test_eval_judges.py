"""Unit tests for harness.eval.judges (prompt-variable mapping + routing).

The live LLM judge calls are exercised at runtime (T5), not here — these cover the
pure adaptation that makes the shared harness/judges/*.md prompts usable by
mlflow.genai.make_judge.
"""

import re

from harness.eval.judges import (
    JUDGE_NAMES,
    _anthropic_judge_base_url,
    load_judge_instructions,
    to_mlflow_instructions,
)

_RESERVED = {"inputs", "outputs", "expectations", "trace", "conversation"}


def test_to_mlflow_instructions_maps_custom_vars():
    src = "CONTEXT:{{context}} QUESTION:{{ question }} ANSWER:{{answer}} GOLD:{{gold_answer}}"
    out = to_mlflow_instructions(src)
    assert "QUESTION:{{ inputs }}" in out
    assert "ANSWER:{{ outputs }}" in out
    assert "GOLD:{{ expectations }}" in out
    # F3: the retrieved context is produced by the RUN (predict_fn returns it in the
    # prediction dict), so it must map to outputs — mapping it to inputs starves the
    # faithfulness judge of context.
    assert "CONTEXT:{{ outputs }}" in out


def test_real_judge_prompts_only_use_reserved_vars_after_mapping():
    for name in JUDGE_NAMES:
        mapped = to_mlflow_instructions(load_judge_instructions(name))
        used = set(re.findall(r"\{\{\s*([a-zA-Z_]+)\s*\}\}", mapped))
        assert used <= _RESERVED, f"{name}: unsupported vars {used - _RESERVED}"


def test_anthropic_judge_base_url(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gw.example.com")
    assert _anthropic_judge_base_url("anthropic:/m") == "https://gw.example.com/v1/messages"
    assert _anthropic_judge_base_url("openai:/m") is None  # only anthropic models
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    assert _anthropic_judge_base_url("anthropic:/m") is None  # no gateway -> default endpoint


def test_judge_route_resolves_role_from_models_yaml():
    from harness.eval.judges import resolve_judge_route

    uri = resolve_judge_route("judge").model
    assert uri.startswith("anthropic:/")  # provider-qualified for mlflow make_judge


def test_ema_judges_ask_for_an_integer(monkeypatch):
    """Judge values were stored as text (e.g. " agent errored") and skipped by the mean."""
    import mlflow.genai.judges as mj

    from harness.eval.judges import ema_judges

    calls = []
    monkeypatch.setattr(mj, "make_judge", lambda **kw: calls.append(kw) or kw["name"])
    judges = ema_judges(model="anthropic:/x")
    assert judges == list(JUDGE_NAMES)
    assert len(calls) == 2
    assert all(c["feedback_value_type"] is int for c in calls)


def test_judge_route_for_each_provider_of_models_yaml():
    """The judge lookup raised for every provider but anthropic; the judge is a setting."""
    from harness.eval.judges import resolve_judge_route

    assert resolve_judge_route(model_key="claude_sonnet").model == "anthropic:/claude-sonnet-5"
    assert resolve_judge_route(model_key="olmo_32b").model == "togetherai:/allenai/OLMo-2-1124-32B-Instruct"
    assert resolve_judge_route(model_key="local_qwen32").model == "openai:/Qwen/Qwen2.5-32B-Instruct"


def test_judge_route_raises_for_a_provider_mlflow_cannot_serve():
    """mlflow fails on the first judge call for an unknown provider; fail at resolution."""
    import pytest

    from harness.eval.judges import judge_route
    from harness.models import ModelConfig

    cfg = ModelConfig(
        model_name="x", description="", provider="no_such_provider",
        model_id="m", max_tokens=1, temperature=0.0,
    )
    with pytest.raises(ValueError, match="no_such_provider"):
        judge_route(cfg)


def test_judge_route_maps_the_key_and_the_endpoint(monkeypatch):
    """mlflow reads TOGETHERAI_API_KEY and OPENAI_API_KEY; this repository sets others."""
    import os

    from harness.eval.judges import apply_judge_key, resolve_judge_route

    # setenv first, so monkeypatch restores the variables mlflow reads after the test.
    monkeypatch.setenv("TOGETHERAI_API_KEY", "stale")
    monkeypatch.setenv("OPENAI_API_KEY", "stale")
    monkeypatch.setenv("TOGETHER_API_KEY", "together-test-value")
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "local-test-value")

    together = resolve_judge_route(model_key="olmo_32b")
    assert together.base_url is None
    apply_judge_key(together)
    assert os.environ["TOGETHERAI_API_KEY"] == os.environ["TOGETHER_API_KEY"]

    local = resolve_judge_route(model_key="local_qwen32")
    assert local.base_url == "http://localhost:8000/v1/chat/completions"
    apply_judge_key(local)
    assert os.environ["OPENAI_API_KEY"] == os.environ["LOCAL_LLM_API_KEY"]


def test_anthropic_judge_sends_the_workspace_header(monkeypatch):
    """mlflow's judge request needs the header too, as extra_headers (mlflow 3.14.0)."""
    import mlflow.genai.judges as mj

    from harness.eval.judges import build_judge

    calls = []
    monkeypatch.setattr(mj, "make_judge", lambda **kw: calls.append(kw))
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "wrkspc_test")
    build_judge("faithfulness", "x {{ outputs }}", model="anthropic:/m")
    build_judge("faithfulness", "x {{ outputs }}", model="openai:/m")
    assert calls[0]["extra_headers"] == {"anthropic-workspace-id": "wrkspc_test"}
    assert "extra_headers" not in calls[1]
