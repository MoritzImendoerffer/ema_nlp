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


def test_judge_model_uri_resolves_role_from_models_yaml():
    from harness.eval.judges import judge_model_uri

    uri = judge_model_uri("judge")
    assert uri.startswith("anthropic:/")  # provider-qualified for mlflow make_judge
