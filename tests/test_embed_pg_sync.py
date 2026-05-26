"""Integration tests for harness.embed_pg.sync() against ema_nlp_test PG
+ a mongomock-backed parsed_documents fixture (MIGR-010).

Requires PG_DSN_TEST set (loaded from ~/.myenvs/ema_nlp.env via python-dotenv)
and mongomock installed. Skipped otherwise — same pattern as
tests/test_retrieve_pg.py.

We stub the Embedder so no BGE model loads; chunks get a deterministic
unit-normalised 1024-d vector keyed by a per-chunk seed.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime

import numpy as np
import pytest
from dotenv import load_dotenv

try:
    import mongomock
    import mongomock.collection as _mc

    _HAS_MONGOMOCK = True
except ImportError:  # pragma: no cover
    _HAS_MONGOMOCK = False
    mongomock = None  # type: ignore[assignment]
    _mc = None  # type: ignore[assignment]

from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from corpus.parsers.base import ParsedDocument
from corpus.sources.parsed_documents import bootstrap_indexes, write_parsed_document
from harness import embed_pg

EMB_DIM = 1024

pytestmark = pytest.mark.skipif(
    not _HAS_MONGOMOCK,
    reason="mongomock not installed",
)


# ---------------------------------------------------------------------------
# Stub Embedder
# ---------------------------------------------------------------------------


class _StubEmbedder:
    """Returns a deterministic unit-normalised vector per text — no model load."""

    def encode(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            seed = int.from_bytes(hashlib.sha256(t.encode("utf-8")).digest()[:4], "big")
            rng = np.random.default_rng(seed)
            v = rng.standard_normal(EMB_DIM).astype(np.float32)
            v /= np.linalg.norm(v) + 1e-12
            out.append(v.tolist())
        return out


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_mongomock_bulk_sort(monkeypatch):
    if not _HAS_MONGOMOCK:
        return
    _orig = _mc.BulkOperationBuilder.add_update

    def _patched(self, *args, sort=None, **kwargs):
        return _orig(self, *args, **kwargs)

    monkeypatch.setattr(_mc.BulkOperationBuilder, "add_update", _patched)


@pytest.fixture(scope="session")
def pg_test_pool():
    """Dedicated pool against PG_DSN_TEST; closed at session end."""
    load_dotenv(os.path.expanduser("~/.myenvs/ema_nlp.env"), override=False)
    dsn = os.getenv("PG_DSN_TEST")
    if not dsn:
        pytest.skip("PG_DSN_TEST not set — skipping sync integration tests")
    try:
        pool = ConnectionPool(
            conninfo=dsn,
            min_size=1,
            max_size=4,
            timeout=10.0,
            configure=lambda c: register_vector(c),
            open=True,
        )
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"Test DB unreachable at {dsn}: {exc}")
    try:
        yield pool
    finally:
        pool.close()


@pytest.fixture(autouse=True)
def _redirect_pool(monkeypatch, pg_test_pool):
    """Make harness.embed_pg.get_pool() return our test pool for the duration
    of each test."""
    monkeypatch.setattr(embed_pg, "get_pool", lambda: pg_test_pool)


@pytest.fixture(autouse=True)
def _clean_pg(pg_test_pool):
    """Wipe documents/chunks/links between tests."""
    with pg_test_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE links, chunks, documents RESTART IDENTITY CASCADE")
        conn.commit()
    yield
    with pg_test_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE links, chunks, documents RESTART IDENTITY CASCADE")
        conn.commit()


@pytest.fixture
def mongo_client():
    if not _HAS_MONGOMOCK:
        pytest.skip("mongomock not installed")
    c = mongomock.MongoClient()
    bootstrap_indexes(client=c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


URLS = [
    "https://www.ema.europa.eu/en/documents/doc-a.pdf",
    "https://www.ema.europa.eu/en/documents/doc-b.pdf",
    "https://www.ema.europa.eu/en/documents/doc-c.pdf",
]

PREF_DEFAULT = {"application/pdf": ["pymupdf4llm"], "text/html": ["trafilatura"]}
PREF_FLIPPED = {"application/pdf": ["llamahub_pdf"], "text/html": ["trafilatura"]}


def _parsed_doc(
    *,
    url: str,
    parser: str = "pymupdf4llm",
    text: str | None = None,
) -> ParsedDocument:
    return ParsedDocument(
        url=url,
        parser=parser,
        parser_version="1.0",
        parsed_at=datetime(2026, 5, 26, 12, 0, tzinfo=UTC),
        content_type="application/pdf",
        text=text
        or (
            "# Title for " + url + "\n\n"
            "EMA/CHMP/12345/2024 Rev. 1\n\n"
            "Body text body text body text. " * 20
        ),
        text_format="markdown",
        error="",
        meta={},
    )


def _seed_parsed_documents(client) -> None:
    """Two parsers per URL × three URLs = 6 rows."""
    for url in URLS:
        for parser in ("pymupdf4llm", "llamahub_pdf"):
            write_parsed_document(
                _parsed_doc(url=url, parser=parser, text=f"# {parser} text for {url}\n\n" + "body " * 50),
                client=client,
            )


def _docs_row_count(pool) -> int:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM documents")
            return cur.fetchone()[0]


def _chunks_row_count(pool) -> int:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM chunks")
            return cur.fetchone()[0]


def _doc_parser_map(pool) -> dict[str, tuple[str, str]]:
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT source_url, parser, parser_version FROM documents")
            return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


# ---------------------------------------------------------------------------
# Test cases (per MIGR-010 acceptance criteria)
# ---------------------------------------------------------------------------


def test_1_initial_sync_writes_documents_and_chunks(mongo_client, pg_test_pool):
    _seed_parsed_documents(mongo_client)
    stats = embed_pg.sync(
        parser_preference=PREF_DEFAULT,
        client=mongo_client,
        embedder=_StubEmbedder(),
        batch_size=4,
    )
    assert stats.new == 3
    assert stats.re_synced == 0
    assert stats.skipped_unchanged == 0
    assert _docs_row_count(pg_test_pool) == 3
    assert _chunks_row_count(pg_test_pool) > 0
    # Every doc carries parser identity
    parsers = _doc_parser_map(pg_test_pool)
    assert set(parsers) == set(URLS)
    for source_url, (parser, version) in parsers.items():
        assert parser == "pymupdf4llm"
        assert version == "1.0"


def test_2_re_sync_with_no_changes_is_a_no_op(mongo_client, pg_test_pool):
    _seed_parsed_documents(mongo_client)
    embed_pg.sync(
        parser_preference=PREF_DEFAULT,
        client=mongo_client,
        embedder=_StubEmbedder(),
        batch_size=4,
    )
    chunks_before = _chunks_row_count(pg_test_pool)

    stats = embed_pg.sync(
        parser_preference=PREF_DEFAULT,
        client=mongo_client,
        embedder=_StubEmbedder(),
        batch_size=4,
    )
    assert stats.skipped_unchanged == 3
    assert stats.new == 0
    assert stats.re_synced == 0
    # No new writes
    assert stats.chunks_written == 0
    assert _chunks_row_count(pg_test_pool) == chunks_before


def test_3_parser_preference_flip_re_syncs_affected_urls(mongo_client, pg_test_pool):
    _seed_parsed_documents(mongo_client)
    embed_pg.sync(
        parser_preference=PREF_DEFAULT,
        client=mongo_client,
        embedder=_StubEmbedder(),
        batch_size=4,
    )

    stats = embed_pg.sync(
        parser_preference=PREF_FLIPPED,
        client=mongo_client,
        embedder=_StubEmbedder(),
        batch_size=4,
    )
    # llamahub_pdf rows have different text → all 3 docs re-sync
    assert stats.re_synced == 3
    assert stats.new == 0
    parsers = _doc_parser_map(pg_test_pool)
    assert all(parser == "llamahub_pdf" for parser, _ in parsers.values())


def test_4_hash_mismatch_triggers_delete_and_reinsert(mongo_client, pg_test_pool):
    """When a URL's parsed_text changes upstream, the doc re-syncs end-to-end."""
    _seed_parsed_documents(mongo_client)
    embed_pg.sync(
        parser_preference=PREF_DEFAULT,
        client=mongo_client,
        embedder=_StubEmbedder(),
        batch_size=4,
    )

    # Mutate one of the pymupdf4llm rows — different text → different hash
    write_parsed_document(
        _parsed_doc(
            url=URLS[0],
            parser="pymupdf4llm",
            text="# New title\n\n" + "fresh body " * 50,
        ),
        client=mongo_client,
    )
    stats = embed_pg.sync(
        parser_preference=PREF_DEFAULT,
        client=mongo_client,
        embedder=_StubEmbedder(),
        batch_size=4,
    )
    # Two unchanged URLs skip, one re-syncs
    assert stats.skipped_unchanged == 2
    assert stats.re_synced == 1


def test_5_legacy_reader_produces_same_pg_state_as_parsed_documents(
    mongo_client, pg_test_pool
):
    """The synthetic legacy reader vs reading parsed_documents directly should
    yield the same documents row count when the same content is in both."""
    # Seed parsed_documents
    for url in URLS:
        write_parsed_document(_parsed_doc(url=url), client=mongo_client)
    # Seed parsed_pdfs (legacy) with the SAME content
    pdfs = mongo_client[embed_pg.MONGO_DB]["parsed_pdfs"]
    for url in URLS:
        pdfs.insert_one(
            {
                "_id": url,
                "markdown": _parsed_doc(url=url).text,
                "error": "",
                "cache_path": "/tmp",
                "ingested_at": "2026-05-26",
            }
        )

    # First: sync via parsed_documents path
    embed_pg.sync(
        parser_preference=PREF_DEFAULT,
        client=mongo_client,
        embedder=_StubEmbedder(),
        batch_size=4,
    )
    chunks_a = _chunks_row_count(pg_test_pool)
    docs_a = _docs_row_count(pg_test_pool)

    # Reset, sync via legacy reader
    with pg_test_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE links, chunks, documents RESTART IDENTITY CASCADE")
        conn.commit()

    embed_pg.sync(
        parser_preference=PREF_DEFAULT,
        client=mongo_client,
        embedder=_StubEmbedder(),
        batch_size=4,
        source="legacy",
    )
    chunks_b = _chunks_row_count(pg_test_pool)
    docs_b = _docs_row_count(pg_test_pool)

    assert docs_a == docs_b
    assert chunks_a == chunks_b


def test_6_url_filter_restricts_sync(mongo_client, pg_test_pool):
    _seed_parsed_documents(mongo_client)
    stats = embed_pg.sync(
        parser_preference=PREF_DEFAULT,
        client=mongo_client,
        embedder=_StubEmbedder(),
        batch_size=4,
        url_filter=[URLS[0]],
    )
    assert stats.new == 1
    assert _docs_row_count(pg_test_pool) == 1


def test_7_dry_run_never_writes(mongo_client, pg_test_pool):
    _seed_parsed_documents(mongo_client)
    stats = embed_pg.sync(
        parser_preference=PREF_DEFAULT,
        client=mongo_client,
        embedder=_StubEmbedder(),
        batch_size=4,
        dry_run=True,
    )
    # All 3 docs are "new" relative to the empty DB
    assert stats.new == 3
    # But the DB is still empty
    assert _docs_row_count(pg_test_pool) == 0
    assert _chunks_row_count(pg_test_pool) == 0
