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
