"""Unit tests for corpus/sources/parsed_documents.py.

Mongo is faked via mongomock (in-memory) so these tests run in CI without a
live MongoDB. Skipped when mongomock isn't installed and MONGO_URI isn't set
— per acceptance criteria for MIGR-001.

mongomock 4.3.0 (the latest released as of 2026-05) hasn't caught up with
pymongo 4.7+'s ``UpdateOne._add_to_bulk`` passing ``sort=`` to
``BulkOperationBuilder.add_update``. We monkey-patch ``add_update`` to drop
the unknown kwarg at the bulk-builder layer for the duration of each test.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

try:
    import mongomock
    import mongomock.collection as _mc

    _HAS_MONGOMOCK = True
except ImportError:  # pragma: no cover - exercised only when extras absent
    _HAS_MONGOMOCK = False
    mongomock = None  # type: ignore[assignment]
    _mc = None  # type: ignore[assignment]

from corpus.parsers.base import ParsedDocument
from corpus.sources import parsed_documents as pd_mod
from corpus.sources.parsed_documents import (
    COLLECTION,
    PARSER_INDEX_NAME,
    UNIQUE_INDEX_NAME,
    URL_INDEX_NAME,
    bootstrap_indexes,
    write_parsed_document,
)

pytestmark = pytest.mark.skipif(
    not _HAS_MONGOMOCK and not os.getenv("MONGO_URI"),
    reason="mongomock not installed and MONGO_URI not set",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_mongomock_bulk_sort(monkeypatch):
    """Drop the ``sort`` kwarg pymongo 4.7+ passes to bulk-add_update.

    mongomock 4.3.0's ``BulkOperationBuilder.add_update`` doesn't yet accept
    ``sort=``; pymongo's ``UpdateOne._add_to_bulk`` always passes it. Patch
    the builder method on a per-test basis so production code is unchanged.
    """
    if not _HAS_MONGOMOCK:
        return
    _orig = _mc.BulkOperationBuilder.add_update

    def _patched(self, *args, sort=None, **kwargs):
        return _orig(self, *args, **kwargs)

    monkeypatch.setattr(_mc.BulkOperationBuilder, "add_update", _patched)


@pytest.fixture
def client():
    """An in-memory mongomock client; falls back to skip when unavailable."""
    if not _HAS_MONGOMOCK:
        pytest.skip("mongomock not installed")
    c = mongomock.MongoClient()
    try:
        yield c
    finally:
        c.close()


def _make_doc(
    *,
    url: str = "https://www.ema.europa.eu/en/example/q-and-a.pdf",
    parser: str = "pymupdf4llm",
    parser_version: str = "1.27.2",
    text: str = "# Title\n\nBody text.",
    text_format: str = "markdown",
    content_type: str = "application/pdf",
    error: str = "",
    meta: dict | None = None,
) -> ParsedDocument:
    return ParsedDocument(
        url=url,
        parser=parser,
        parser_version=parser_version,
        parsed_at=datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC),
        content_type=content_type,
        text=text,
        text_format=text_format,  # type: ignore[arg-type]
        error=error,
        meta=meta or {},
    )


def _col(client):
    return client[pd_mod.MONGO_DB][COLLECTION]


# ---------------------------------------------------------------------------
# bootstrap_indexes
# ---------------------------------------------------------------------------


def test_bootstrap_indexes_creates_all_three(client):
    bootstrap_indexes(client=client)
    names = set(_col(client).index_information().keys())
    assert UNIQUE_INDEX_NAME in names
    assert URL_INDEX_NAME in names
    assert PARSER_INDEX_NAME in names


def test_bootstrap_indexes_is_idempotent(client):
    bootstrap_indexes(client=client)
    bootstrap_indexes(client=client)  # second call must not raise
    names = set(_col(client).index_information().keys())
    assert UNIQUE_INDEX_NAME in names


# ---------------------------------------------------------------------------
# write_parsed_document
# ---------------------------------------------------------------------------


def test_single_write_round_trips(client):
    bootstrap_indexes(client=client)
    doc = _make_doc(meta={"cache_path": "/tmp/x.pdf", "ingested_at": "2026-05-26"})
    result = write_parsed_document(doc, client=client)
    assert result == {"matched": 0, "modified": 0, "upserted": 1}

    stored = _col(client).find_one(
        {"url": doc.url, "parser": doc.parser, "parser_version": doc.parser_version}
    )
    assert stored is not None
    # All non-datetime fields survive the round-trip verbatim
    for field_name in (
        "url",
        "parser",
        "parser_version",
        "content_type",
        "text",
        "text_format",
        "error",
    ):
        assert stored[field_name] == getattr(doc, field_name), field_name
    assert stored["meta"] == doc.meta
    # BSON drops tzinfo (Mongo stores naive UTC). Compare the UTC instant.
    stored_parsed_at = stored["parsed_at"]
    if stored_parsed_at.tzinfo is None:
        stored_parsed_at = stored_parsed_at.replace(tzinfo=UTC)
    assert stored_parsed_at == doc.parsed_at


def test_duplicate_key_is_upsert_not_insert(client):
    bootstrap_indexes(client=client)
    doc1 = _make_doc(text="first text")
    doc2 = _make_doc(text="second text")  # same (url, parser, parser_version)

    r1 = write_parsed_document(doc1, client=client)
    r2 = write_parsed_document(doc2, client=client)

    assert r1["upserted"] == 1
    assert r2["upserted"] == 0
    assert r2["matched"] == 1
    assert r2["modified"] == 1
    assert _col(client).count_documents({}) == 1

    stored = _col(client).find_one({})
    assert stored["text"] == "second text"  # last write wins


def test_different_parser_versions_coexist(client):
    bootstrap_indexes(client=client)
    url = "https://www.ema.europa.eu/en/example/q-and-a.pdf"
    doc_v1 = _make_doc(url=url, parser_version="1.27.2", text="v1")
    doc_v2 = _make_doc(url=url, parser_version="1.28.0", text="v2")

    write_parsed_document(doc_v1, client=client)
    write_parsed_document(doc_v2, client=client)

    assert _col(client).count_documents({"url": url}) == 2
    versions = {d["parser_version"] for d in _col(client).find({"url": url})}
    assert versions == {"1.27.2", "1.28.0"}


def test_different_parsers_coexist_for_same_url(client):
    bootstrap_indexes(client=client)
    url = "https://www.ema.europa.eu/en/example/q-and-a.pdf"
    doc_a = _make_doc(url=url, parser="pymupdf4llm", text="A")
    doc_b = _make_doc(url=url, parser="llamahub_pdf", text="B")

    write_parsed_document(doc_a, client=client)
    write_parsed_document(doc_b, client=client)

    parsers = {d["parser"] for d in _col(client).find({"url": url})}
    assert parsers == {"pymupdf4llm", "llamahub_pdf"}


# ---------------------------------------------------------------------------
# Malformed input — ValueError before any Mongo interaction
# ---------------------------------------------------------------------------


def test_constructing_with_empty_url_raises():
    with pytest.raises(ValueError, match="url"):
        _make_doc(url="")


def test_constructing_with_empty_parser_raises():
    with pytest.raises(ValueError, match="parser"):
        _make_doc(parser="")


def test_constructing_with_bad_text_format_raises():
    with pytest.raises(ValueError, match="text_format"):
        _make_doc(text_format="rst")


def test_constructing_with_non_datetime_parsed_at_raises():
    with pytest.raises(ValueError, match="parsed_at"):
        ParsedDocument(
            url="u",
            parser="p",
            parser_version="v",
            parsed_at="2026-05-26",  # type: ignore[arg-type]
            content_type="application/pdf",
            text="t",
            text_format="markdown",
        )


def test_write_rejects_non_parsed_document_before_touching_mongo(client):
    bootstrap_indexes(client=client)
    with pytest.raises(ValueError, match="ParsedDocument"):
        write_parsed_document({"url": "u"}, client=client)  # type: ignore[arg-type]
    assert _col(client).count_documents({}) == 0


def test_write_rejects_mutated_parsed_document_before_touching_mongo(client):
    """A ParsedDocument constructed valid then mutated to invalid must fail
    at the writer boundary, not silently corrupt Mongo."""
    bootstrap_indexes(client=client)
    doc = _make_doc()
    doc.url = ""  # mutate to invalid state
    with pytest.raises(ValueError, match="url"):
        write_parsed_document(doc, client=client)
    assert _col(client).count_documents({}) == 0
