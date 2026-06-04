"""Unit tests for the Chainlit dynamic strategy selector (CSEL-001/003/004).

Covers the pure, registry-driven helpers in app.py (the Chainlit handlers themselves
are verified manually — there is no headless Chainlit harness here). Phoenix is
disabled at import so app.py does not register a collector.
"""

from __future__ import annotations

import os

os.environ.setdefault("PHOENIX_DISABLED", "1")

import app  # noqa: E402
from harness.workflows.registry import WORKFLOW_REGISTRY, get_workflow, list_workflows  # noqa: E402
from harness.workflows.utils import list_prompt_strategies  # noqa: E402


class _Fake:
    """Stand-in retriever/llm — any attribute access / call returns self."""

    def __getattr__(self, _):
        return self

    def __call__(self, *a, **k):
        return self


# ── dynamic discovery: options mirror the registries ─────────────────────────

def test_chat_options_mirror_registries():
    opts = app._chat_options()
    assert set(opts["workflows"]) == set(list_workflows())
    assert opts["prompt_strategies"] == list_prompt_strategies()
    assert "neo4j_hier" in opts["index_profiles"]


def test_new_workflow_auto_appears(monkeypatch):
    # registering a workflow makes it show up in the panel with no app.py edit
    monkeypatch.setitem(WORKFLOW_REGISTRY, "fancy_rag", lambda r, l, **k: None)
    assert "fancy_rag" in app._chat_options()["workflows"]
    assert app._workflow_label("fancy_rag") == "Fancy Rag"  # title-cased fallback label


def test_workflow_label_known_and_fallback():
    assert app._workflow_label("simple_rag") == "Simple RAG"
    assert app._workflow_label("brand_new_thing") == "Brand New Thing"


# ── settings -> pipeline kwargs ──────────────────────────────────────────────

def test_settings_to_pipeline_kwargs_maps_selectors():
    kw = app._settings_to_pipeline_kwargs({
        "workflow": "crag", "prompt_strategy": "cot_self", "index_profile": "neo4j_hier",
        "agent_model": "claude_haiku", "temperature": 0.3, "retrieval_k": 7,
    })
    assert kw == {
        "strategy": "crag", "prompt_strategy": "cot_self", "index_profile": "neo4j_hier",
        "model_name": "claude_haiku", "temperature": 0.3, "retrieval_k": 7,
    }


def test_settings_to_pipeline_kwargs_defaults():
    kw = app._settings_to_pipeline_kwargs({})
    assert kw["strategy"] == app.WORKFLOW_STRATEGY
    assert kw["prompt_strategy"] == "zero_shot"
    assert kw["index_profile"] == app.EMA_INDEX_PROFILE


# ── panel construction seeds every widget (A6) ───────────────────────────────

def test_make_chat_settings_widgets_and_initials():
    seed = app._seed_settings("react", None, "neo4j_hier")
    by = {w.id: w for w in app._make_chat_settings(seed).inputs}
    assert set(by) == {
        "workflow", "prompt_strategy", "index_profile",
        "agent_model", "temperature", "retrieval_k", "cache_enabled",
    }
    assert by["workflow"].initial == "react"
    assert by["prompt_strategy"].initial == "zero_shot"
    assert by["index_profile"].initial == "neo4j_hier"
    assert by["temperature"].initial == 0.0
    assert by["cache_enabled"].initial is True


# ── CSEL-001 regression: react/react_review tolerate a forwarded prompt_strategy ─

def test_react_builders_tolerate_prompt_strategy():
    # would TypeError before DL4 (builders had no prompt_strategy/**kwargs)
    assert get_workflow("react", retriever=_Fake(), llm=_Fake(), prompt_strategy="cot_self")
    assert get_workflow("react_review", retriever=_Fake(), llm=_Fake(), prompt_strategy="few_shot")
