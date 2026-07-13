"""Shared test fixtures.

mongomock 4.3.0 (latest as of 2026-05) hasn't caught up with pymongo 4.7+'s
``UpdateOne._add_to_bulk`` passing ``sort=`` to
``BulkOperationBuilder.add_update``. Autouse-patch the builder to drop the
unknown kwarg so every mongomock-backed test can use ``bulk_write`` upserts
(test_parsed_documents_writer carries a local copy of this fixture from before
this conftest existed; the two compose harmlessly).
"""

from __future__ import annotations

import pytest

try:
    import mongomock.collection as _mc

    _HAS_MONGOMOCK = True
except ImportError:  # pragma: no cover
    _HAS_MONGOMOCK = False
    _mc = None  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _mongomock_bulk_sort_compat(monkeypatch):
    if not _HAS_MONGOMOCK:
        return
    _orig = _mc.BulkOperationBuilder.add_update

    def _patched(self, *args, sort=None, **kwargs):
        return _orig(self, *args, **kwargs)

    monkeypatch.setattr(_mc.BulkOperationBuilder, "add_update", _patched)
