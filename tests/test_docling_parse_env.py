"""Tests that run in the Docling parse environment only (`make test-parse`), never in the gate.

The gate deselects them by marker (`make test`: `-m "not integration and not parse"`), and
each skips when Docling is not importable, so a plain `pytest` in .venv stays green.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.parse

docling = pytest.importorskip("docling")


def test_pinned_versions():
    from importlib.metadata import version

    assert version("docling") == "2.153.0"
    assert version("rapidocr") == "3.10.0"
    assert version("torch").startswith("2.15.0")


def test_retrieval_env_is_not_this_env():
    import sys

    assert ".venv" not in sys.prefix.split("/")
