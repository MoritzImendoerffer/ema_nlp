"""Tests for harness/models.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from harness.models import ModelConfig, call_model, load_model_for_role

# ---------------------------------------------------------------------------
# load_model_for_role
# ---------------------------------------------------------------------------

def test_load_model_for_all_roles():
    roles = ["agent", "grader", "rewriter", "reranker", "judge", "reviewer"]
    for role in roles:
        cfg = load_model_for_role(role)
        assert cfg.model_name
        assert cfg.model_id
        assert cfg.provider in ("anthropic", "together_ai", "openai_compatible")
        assert cfg.max_tokens > 0


def test_load_model_for_role_unknown_raises():
    with pytest.raises(ValueError, match="Unknown role"):
        load_model_for_role("nonexistent_role")


def test_agent_role_is_opus():
    cfg = load_model_for_role("agent")
    assert "opus" in cfg.model_id.lower()
    assert cfg.provider == "anthropic"


def test_judge_role_is_opus():
    cfg = load_model_for_role("judge")
    assert "opus" in cfg.model_id.lower()
    assert cfg.provider == "anthropic"


def test_reviewer_role_is_opus():
    cfg = load_model_for_role("reviewer")
    assert "opus" in cfg.model_id.lower()


# ---------------------------------------------------------------------------
# call_model — Anthropic path (mocked)
# ---------------------------------------------------------------------------

def test_call_model_anthropic_agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    fake_content = MagicMock()
    fake_content.text = "response text"
    fake_msg = MagicMock()
    fake_msg.content = [fake_content]

    with patch("anthropic.Anthropic") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = fake_msg
        mock_client_cls.return_value = mock_client

        result = call_model("Hello", "agent")

    assert result == "response text"
    mock_client.messages.create.assert_called_once()


def test_call_model_anthropic_missing_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(OSError, match="ANTHROPIC_API_KEY"):
        call_model("Hello", "agent")


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

        call_model("Hello", "agent", system="You are a helpful assistant.")
        call_kwargs = mock_client.messages.create.call_args[1]
        assert "system" in call_kwargs


# ---------------------------------------------------------------------------
# call_model — Together AI / OLMo path (mocked via openai)
# ---------------------------------------------------------------------------

def test_call_model_together_missing_key(monkeypatch):
    monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
    # Use config override to force together_ai provider
    cfg = ModelConfig(
        model_name="olmo_32b",
        description="test",
        provider="together_ai",
        model_id="allenai/OLMo-2-1124-32B-Instruct",
        max_tokens=512,
        temperature=0.0,
    )
    with pytest.raises(OSError, match="TOGETHER_API_KEY"):
        call_model("Hello", config=cfg)


def test_call_model_together_olmo(monkeypatch):
    monkeypatch.setenv("TOGETHER_API_KEY", "test-together-key")
    fake_msg = MagicMock()
    fake_msg.choices[0].message.content = "olmo response"

    cfg = ModelConfig(
        model_name="olmo_32b",
        description="test",
        provider="together_ai",
        model_id="allenai/OLMo-2-1124-32B-Instruct",
        max_tokens=2048,
        temperature=0.0,
    )

    with patch("openai.OpenAI") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = fake_msg
        mock_client_cls.return_value = mock_client

        result = call_model("Hello", config=cfg)

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

        call_model("Hi", "agent", model_id_override="claude-sonnet-4-6")
        create_kwargs = mock_client.messages.create.call_args[1]
        assert create_kwargs["model"] == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# models.yaml schema validation
# ---------------------------------------------------------------------------

def test_models_yaml_has_all_models():
    yaml_path = Path(__file__).parent.parent / "harness" / "configs" / "models.yaml"
    data = yaml.safe_load(yaml_path.read_text())
    assert "models" in data, "models: section missing from models.yaml"
    assert "roles" in data, "roles: section missing from models.yaml"

    expected_models = {"claude_haiku", "claude_opus", "olmo_32b", "local_qwen32"}
    assert expected_models <= set(data["models"]), (
        f"Missing model entries: {expected_models - set(data['models'])}"
    )

    for name, m in data["models"].items():
        assert "model_id" in m, f"model {name} missing model_id"
        assert "provider" in m, f"model {name} missing provider"
        assert "max_tokens" in m, f"model {name} missing max_tokens"


def test_models_yaml_roles_resolve():
    """Every role must map to a model that exists in models:."""
    yaml_path = Path(__file__).parent.parent / "harness" / "configs" / "models.yaml"
    data = yaml.safe_load(yaml_path.read_text())
    for role, model_name in data["roles"].items():
        assert model_name in data["models"], (
            f"Role '{role}' maps to '{model_name}' which is not in models:"
        )


def test_openai_compatible_model_has_api_base():
    yaml_path = Path(__file__).parent.parent / "harness" / "configs" / "models.yaml"
    data = yaml.safe_load(yaml_path.read_text())
    for name, m in data["models"].items():
        if m["provider"] == "openai_compatible":
            assert "api_base" in m, f"openai_compatible model '{name}' missing api_base"


def test_load_model_config_by_key():
    from harness.models import load_model_config

    assert load_model_config("claude_sonnet").model_id == "claude-sonnet-5"
    with pytest.raises(ValueError):
        load_model_config("no_such_model")


def test_no_recipe_generates_with_the_judge_model():
    """Every stored number was judged by the model that generated it (decision E)."""
    from harness.models import load_model_config
    from harness.recipes.config import load_recipe

    judge_id = load_model_for_role("judge").model_id
    recipe_dir = Path(__file__).parent.parent / "harness" / "configs" / "recipes"
    files = sorted(recipe_dir.glob("*.yaml"))
    assert len(files) == 10
    for path in files:
        recipe = load_recipe(path.stem)
        assert load_model_config(recipe.model).model_id != judge_id, path.name


def test_workspace_header_only_when_the_variable_is_set(monkeypatch):
    """An organization-scoped key needs anthropic-workspace-id; a workspace key needs nothing."""
    from harness.models import anthropic_headers

    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID", raising=False)
    assert anthropic_headers() == {}
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", " wrkspc_test ")
    assert anthropic_headers() == {"anthropic-workspace-id": "wrkspc_test"}


def test_call_anthropic_sends_the_workspace_header(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "wrkspc_test")
    fake_content = MagicMock()
    fake_content.text = "ok"
    with patch("anthropic.Anthropic") as mock_client_cls:
        mock_client_cls.return_value.messages.create.return_value = MagicMock(content=[fake_content])
        call_model("Hello", "agent")
    headers = mock_client_cls.call_args.kwargs["default_headers"]
    assert headers == {"anthropic-workspace-id": "wrkspc_test"}
