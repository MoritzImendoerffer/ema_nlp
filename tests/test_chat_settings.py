"""Unit tests for the Chainlit recipe selector (app.py helpers).

Covers the pure, registry-driven helpers in app.py (the Chainlit handlers themselves are
verified manually — there is no headless Chainlit harness here). Tracing is disabled at
import so app.py does not connect to an MLflow tracking server.
"""

from __future__ import annotations

import os

os.environ.setdefault("EMA_TRACING_DISABLED", "1")

import app  # noqa: E402
from harness.recipes import list_recipes  # noqa: E402

_BUILTINS = {
    "naive_rag", "crag_agentic", "react_agentic", "regulatory_agent",
    "agentic_reranked", "agentic_judged", "regulatory_fewshot",
}


# ── recipe discovery mirrors the registry ─────────────────────────────────────

def test_recipe_items_mirror_registry():
    items = app._recipe_items()
    assert _BUILTINS <= set(items)
    assert set(items) == set(list_recipes())
    assert items["naive_rag"]  # non-empty display label


def test_resolve_recipe_name():
    assert app._resolve_recipe_name("crag_agentic") == "crag_agentic"
    # unknown / empty fall back to the registry default
    assert app._resolve_recipe_name("does_not_exist") == app._resolve_recipe_name(None)
    assert app._resolve_recipe_name("") == app._resolve_recipe_name(None)
    assert app._resolve_recipe_name(None) in set(list_recipes())


# ── settings -> kwargs ────────────────────────────────────────────────────────

def test_settings_to_kwargs_maps_recipe_and_overrides():
    kw = app._settings_to_kwargs(
        {"recipe": "crag_agentic", "model": "claude_haiku", "temperature": 0.3, "retrieval_k": 7}
    )
    assert kw == {
        "recipe_name": "crag_agentic",
        "model": "claude_haiku",
        "temperature": 0.3,
        "retrieval_k": 7,
    }


def test_settings_to_kwargs_defaults():
    kw = app._settings_to_kwargs({})
    assert kw["recipe_name"] in set(list_recipes())
    assert kw["model"] == "claude_opus"
    assert kw["retrieval_k"] == app.RETRIEVAL_K


# ── panel construction seeds every widget ─────────────────────────────────────

def test_make_chat_settings_widgets_and_initials():
    seed = app._seed_settings("crag_agentic")
    by = {w.id: w for w in app._make_chat_settings(seed).inputs}
    assert set(by) == {"recipe", "model", "temperature", "retrieval_k", "cache_enabled"}
    assert by["recipe"].initial == "crag_agentic"
    assert by["cache_enabled"].initial is True


def test_seed_settings_uses_recipe_defaults():
    seed = app._seed_settings("naive_rag")
    assert seed["recipe"] == "naive_rag"
    assert seed["model"] == "claude_opus"  # the recipe's model
    assert seed["temperature"] == 0.0
    assert seed["cache_enabled"] is True


# ── source-reference persistence + re-openability (side-panel bug fix) ────────

def test_local_storage_client_roundtrip(tmp_path):
    """Elements persist to disk under a /public URL (without a storage client the
    SQLAlchemy data layer silently drops elements → sources vanish on resume)."""
    import asyncio

    import app as app_mod

    client = app_mod._LocalStorageClient(tmp_path / "elements")
    out = asyncio.run(client.upload_file("user/el-1/Q1 · Src 1", "card", "text/plain"))
    assert out["object_key"] == "user/el-1/Q1 · Src 1"
    assert out["url"].startswith("/public/elements/user/el-1/Q1")
    assert (tmp_path / "elements" / "user" / "el-1" / "Q1 · Src 1").read_text() == "card"
    assert asyncio.run(client.delete_file("user/el-1/Q1 · Src 1")) is True


def test_local_storage_client_blocks_path_escape(tmp_path):
    import asyncio

    import pytest

    import app as app_mod

    client = app_mod._LocalStorageClient(tmp_path / "elements")
    with pytest.raises(ValueError, match="object key"):
        asyncio.run(client.upload_file("../outside", "x"))


def test_data_layer_has_storage_provider():
    import app as app_mod

    layer = app_mod.get_data_layer()
    assert layer.storage_provider is not None  # else create_element drops every element
