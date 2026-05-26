"""Tests for scripts/migrate_mongo_to_parsed_documents.py (MIGR-012)."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

try:
    import mongomock
    import mongomock.collection as _mc

    _HAS_MONGOMOCK = True
except ImportError:  # pragma: no cover
    _HAS_MONGOMOCK = False
    mongomock = None  # type: ignore[assignment]
    _mc = None  # type: ignore[assignment]

from corpus.sources import parsed_documents as pd_mod

# Load the script as a module so we can call run_migration directly.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "migrate_mongo_to_parsed_documents",
    _REPO_ROOT / "scripts" / "migrate_mongo_to_parsed_documents.py",
)
assert _spec is not None and _spec.loader is not None
migrate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migrate)

FIXTURES = Path(__file__).parent / "fixtures"
HTML_SAMPLE = (FIXTURES / "ema_html_sample.html").read_text(encoding="utf-8")
HTML_LANDING = (FIXTURES / "ema_nav_landing.html").read_text(encoding="utf-8")

PDF_URL_A = "https://www.ema.europa.eu/en/documents/a.pdf"
PDF_URL_B = "https://www.ema.europa.eu/en/documents/b.pdf"
HTML_URL = "https://www.ema.europa.eu/en/qa-page"

pytestmark = pytest.mark.skipif(
    not _HAS_MONGOMOCK and not os.getenv("MONGO_URI"),
    reason="mongomock not installed and MONGO_URI not set",
)


@pytest.fixture(autouse=True)
def _patch_mongomock_bulk_sort(monkeypatch):
    if not _HAS_MONGOMOCK:
        return
    _orig = _mc.BulkOperationBuilder.add_update

    def _patched(self, *args, sort=None, **kwargs):
        return _orig(self, *args, **kwargs)

    monkeypatch.setattr(_mc.BulkOperationBuilder, "add_update", _patched)


@pytest.fixture
def client():
    if not _HAS_MONGOMOCK:
        pytest.skip("mongomock not installed")
    c = mongomock.MongoClient()
    yield c
    c.close()


def _seed(client):
    pdfs = client[pd_mod.MONGO_DB]["parsed_pdfs"]
    pdfs.insert_many(
        [
            {"_id": PDF_URL_A, "markdown": "# A\n\n" + "body " * 50, "error": ""},
            {"_id": PDF_URL_B, "markdown": "# B\n\n" + "body " * 50, "error": ""},
            {"_id": PDF_URL_A + "#err", "markdown": "", "error": "parser_crashed"},
        ]
    )
    web = client[pd_mod.MONGO_DB]["web_items"]
    web.insert_many(
        [
            {
                "_id": HTML_URL,
                "url": [HTML_URL],
                "content_type": "text/html",
                "html_raw": [HTML_SAMPLE],
            },
            {
                "_id": HTML_URL + "/landing",
                "url": [HTML_URL + "/landing"],
                "content_type": "text/html",
                "html_raw": [HTML_LANDING],
            },
        ]
    )


def _parsed_documents_count(client) -> int:
    return client[pd_mod.MONGO_DB]["parsed_documents"].count_documents({})


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_backfill_writes_pdf_and_html_rows(client):
    _seed(client)
    counts = migrate.run_migration(source="both", client=client)
    assert counts["read"] >= 3  # 2 good PDFs + 1 HTML (landing filtered)
    assert counts["written"] >= 3
    assert _parsed_documents_count(client) >= 3


def test_backfill_pdfs_only(client):
    _seed(client)
    counts = migrate.run_migration(source="pdfs", client=client)
    assert counts["written"] == 2  # error PDF filtered
    coll = client[pd_mod.MONGO_DB]["parsed_documents"]
    parsers = {r["parser"] for r in coll.find()}
    assert parsers == {"pymupdf4llm"}


def test_backfill_html_only(client):
    _seed(client)
    counts = migrate.run_migration(source="html", client=client)
    assert counts["written"] == 1  # landing page filtered
    coll = client[pd_mod.MONGO_DB]["parsed_documents"]
    parsers = {r["parser"] for r in coll.find()}
    assert parsers == {"trafilatura"}


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_backfill_is_idempotent(client):
    _seed(client)
    migrate.run_migration(source="both", client=client)
    before = _parsed_documents_count(client)
    migrate.run_migration(source="both", client=client)
    after = _parsed_documents_count(client)
    assert before == after


# ---------------------------------------------------------------------------
# Filters / flags
# ---------------------------------------------------------------------------


def test_dry_run_does_not_write(client):
    _seed(client)
    counts = migrate.run_migration(source="both", client=client, dry_run=True)
    assert counts["written"] >= 3  # counted as would-write
    assert _parsed_documents_count(client) == 0


def test_limit_caps_reads(client):
    _seed(client)
    counts = migrate.run_migration(source="both", client=client, limit=1)
    assert counts["written"] == 1


def test_invalid_source_raises(client):
    with pytest.raises(ValueError, match="source"):
        migrate.run_migration(source="invalid", client=client)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_error_rows_skipped(client):
    """Error rows from parsed_pdfs are filtered out by the legacy reader."""
    _seed(client)
    migrate.run_migration(source="pdfs", client=client)
    urls = {r["url"] for r in client[pd_mod.MONGO_DB]["parsed_documents"].find()}
    assert PDF_URL_A + "#err" not in urls


def test_landing_pages_skipped(client):
    """HTML landing pages don't reach parsed_documents."""
    _seed(client)
    migrate.run_migration(source="html", client=client)
    urls = {r["url"] for r in client[pd_mod.MONGO_DB]["parsed_documents"].find()}
    assert (HTML_URL + "/landing") not in urls
