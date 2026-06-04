"""Unit tests for the registry-level open_index dispatch (CSEL-002 / RETRIEVAL_TRACKS §0.7 P0)."""

from __future__ import annotations

import pytest

from harness.indexing import open_index, register_open
from harness.indexing.profiles import IndexConfig, IndexProfile, RetrievalConfig
from harness.indexing.registry import OPEN_BUILDERS


def _profile(kind: str) -> IndexProfile:
    return IndexProfile(name="t", index=IndexConfig(kind=kind), retrieval=RetrievalConfig())


def test_property_graph_registered_on_import():
    # importing harness.indexing fires property_graph's @register_open decorator
    assert "property_graph" in OPEN_BUILDERS


def test_property_graph_open_index_not_renamed():
    # A2: the module-level function must stay importable for the 5 existing call sites
    from harness.indexing.property_graph import open_index as pg_open
    assert callable(pg_open)


def test_open_dispatch_routes_on_kind():
    sentinel = object()

    @register_open("__test_open_kind__")
    def _opener(profile, **kw):
        return (sentinel, profile.index.kind, kw)

    try:
        out = open_index(_profile("__test_open_kind__"), foo=1)
        assert out == (sentinel, "__test_open_kind__", {"foo": 1})
    finally:
        OPEN_BUILDERS.pop("__test_open_kind__", None)


def test_open_unknown_kind_raises():
    with pytest.raises(NotImplementedError, match="__nope__"):
        open_index(_profile("__nope__"))
