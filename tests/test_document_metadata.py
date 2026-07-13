"""Unit tests for harness.indexing.document_metadata (mongomock)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import mongomock
import pytest

from config import MONGO_DB
from harness.indexing.document_metadata import (
    COLLECTION,
    mongo_metadata_lookup,
    upsert_badges,
    upsert_doc_types,
)

_HTML_URL = "https://www.ema.europa.eu/en/human-regulatory/overview/pharmacovigilance"
_PDF_URL = "https://www.ema.europa.eu/en/documents/scientific-guideline/gvp-module-v_en.pdf"
_AT = datetime(2026, 7, 13, tzinfo=UTC)


@pytest.fixture
def client():
    return mongomock.MongoClient()


def _rows(client):
    return list(client[MONGO_DB][COLLECTION].find({}))


def test_upsert_badges_writes_row_with_doc_id_and_provenance(client):
    n = upsert_badges(
        [{"url": _HTML_URL, "audience": "Human", "site_topic": "Pharmacovigilance"}],
        client=client, stamped_at=_AT,
    )
    assert n == 1
    (row,) = _rows(client)
    assert row["doc_id"] == hashlib.sha256(_HTML_URL.encode()).hexdigest()
    assert row["audience"] == "Human"
    assert row["site_topic"] == "Pharmacovigilance"
    # Mongo stores datetimes tz-naive (UTC implied)
    assert row["provenance"]["badges"]["stamped_at"].replace(tzinfo=None) == _AT.replace(tzinfo=None)
    assert "doc_type" not in row  # the badge pass never touches the other group


def test_badge_nulls_overwrite_stale_values(client):
    upsert_badges([{"url": _HTML_URL, "audience": "Human", "site_topic": "X"}], client=client)
    upsert_badges([{"url": _HTML_URL, "audience": None, "site_topic": None}], client=client)
    (row,) = _rows(client)
    assert row["audience"] is None and row["site_topic"] is None


def test_doc_type_and_badge_passes_compose_on_one_row(client):
    upsert_badges([{"url": _PDF_URL, "audience": None, "site_topic": None}], client=client)
    upsert_doc_types({_PDF_URL: "scientific-guideline"}, client=client, stamped_at=_AT)
    (row,) = _rows(client)  # same URL -> ONE row, both label groups
    assert row["doc_type"] == "scientific-guideline"
    assert set(row["provenance"]) == {"badges", "doc_type"}


def test_upserts_are_idempotent_no_duplicate_rows(client):
    for _ in range(2):
        upsert_doc_types({_PDF_URL: "scientific-guideline"}, client=client)
    assert len(_rows(client)) == 1


def test_empty_export_type_stored_as_none(client):
    upsert_doc_types({_PDF_URL: ""}, client=client)
    (row,) = _rows(client)
    assert row["doc_type"] is None


def test_lookup_returns_row_or_none(client):
    upsert_doc_types({_PDF_URL: "assessment-report"}, client=client)
    lookup = mongo_metadata_lookup(client)
    assert lookup(_PDF_URL)["doc_type"] == "assessment-report"
    assert lookup("https://www.ema.europa.eu/en/never-enriched") is None


def test_batching_flushes_all_rows(client):
    urls = {f"https://www.ema.europa.eu/en/documents/d{i}_en.pdf": "report" for i in range(7)}
    assert upsert_doc_types(urls, client=client, batch_size=3) == 7
    assert len(_rows(client)) == 7
