"""Integration tests for harness/retrieve_pg.py against a real Postgres DB
(NARR-026).

Requires the ``PG_DSN_TEST`` environment variable, e.g. via ``~/.myenvs/ema_nlp.env``::

    PG_DSN_TEST=postgresql://ema_nlp:<password>@localhost:5432/ema_nlp_test

Setup (one-time, idempotent)::

    docker exec ema_nlp_pg psql -U ema_nlp -d ema_nlp -c \\
        "CREATE DATABASE ema_nlp_test;"
    docker exec -i ema_nlp_pg psql -U ema_nlp -d ema_nlp_test \\
        < corpus/pg_schema.sql

The session fixture wipes and reseeds the three tables (``documents``,
``chunks``, ``links``) with a deterministic 10-chunk / 3-doc / 2-link corpus.
We synthesise the 1024-dim embeddings ourselves and monkey-patch
``_query_embedding`` so the tests don't need the BGE model on disk.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime

import numpy as np
import pytest
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from harness import retrieve_pg as rp
from harness.retrieve_pg import (
    PrefilterConfig,
    RetrievalConfigPG,
    TraversalConfig,
    retrieve_bm25_pg,
    retrieve_dense_pg,
    retrieve_hybrid_pg,
    retrieve_with_config_pg,
)

# ---------------------------------------------------------------------------
# Fixture corpus
# ---------------------------------------------------------------------------

EMB_DIM = 1024

# 3 documents — one CHMP PDF, one PRAC PDF, one HTML.
DOCS = [
    {
        "source_url": "https://test.local/ema/chmp/doc-a.pdf",
        "source_type": "pdf",
        "title": "CHMP guideline on nitrosamine impurities",
        "topic_path": "/en/documents/scientific-guideline/",
        "reference_number": "EMA/CHMP/00001/2024",
        "committee": "CHMP",
        "revision": "1",
        "last_updated": datetime(2024, 3, 1, tzinfo=UTC),
    },
    {
        "source_url": "https://test.local/ema/prac/doc-b.pdf",
        "source_type": "pdf",
        "title": "PRAC pharmacovigilance assessment",
        "topic_path": "/en/documents/scientific-guideline/",
        "reference_number": "EMA/PRAC/00002/2024",
        "committee": "PRAC",
        "revision": None,
        "last_updated": datetime(2024, 6, 15, tzinfo=UTC),
    },
    {
        "source_url": "https://test.local/ema/html/doc-c",
        "source_type": "html",
        "title": "Acceptable Intake values — questions and answers",
        "topic_path": "/en/human-regulatory/",
        "reference_number": None,
        "committee": None,
        "revision": None,
        "last_updated": datetime(2023, 12, 5, tzinfo=UTC),
    },
]

# 10 chunks — 4 for doc-a (CHMP), 3 for doc-b (PRAC), 3 for doc-c (HTML).
# Each chunk has a unique keyword so BM25 can target it precisely.
CHUNKS = [
    # doc-a (CHMP)
    ("a", 0, "Nitrosamine acceptable intake limits for CHMP applicants.", "## 1. Limits"),
    ("a", 1, "Pharmacovigilance plan submission requires CHMP review.", "## 2. Submission"),
    ("a", 2, "Reference to EMA/PRAC/00002/2024 for assessment guidance.", "## 3. Cross-ref"),
    ("a", 3, "See related guidance at https://test.local/ema/prac/doc-b.pdf for more.", "## 4. See also"),
    # doc-b (PRAC)
    ("b", 0, "Pharmacovigilance system master file PSMF assessment criteria.", "## A. Criteria"),
    ("b", 1, "Signal detection methodology for post-authorisation safety studies.", "## B. Methodology"),
    ("b", 2, "Risk minimisation measures and additional monitoring obligations.", "## C. Risk"),
    # doc-c (HTML)
    ("c", 0, "Acceptable Intake values are derived from carcinogenicity TD50 data.", None),
    ("c", 1, "Linear Extrapolation method as defined in ICH M7 underpins the calculation.", None),
    ("c", 2, "Monitoring obligations apply when limits exceed permitted daily exposure.", None),
]


def _doc_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _chunk_id(doc_id: str, idx: int, text: str) -> str:
    raw = f"{doc_id}||{idx}||{text.strip()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _deterministic_embedding(seed: int) -> np.ndarray:
    """Reproducible unit-normalised 1024-dim vector keyed by seed."""
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(EMB_DIM).astype(np.float32)
    vec /= np.linalg.norm(vec) + 1e-12
    return vec


def _seed_corpus(pool: ConnectionPool) -> dict:
    """Wipe + reseed the test corpus. Returns a mapping of chunk_id → metadata
    the tests use to assert on retrieval results."""
    doc_id_by_letter: dict[str, str] = {}
    chunk_id_by_letter_idx: dict[tuple[str, int], str] = {}
    chunk_meta: dict[str, dict] = {}

    with pool.connection() as conn:
        with conn.cursor() as cur:
            # Clean slate. CASCADE removes chunks + links.
            cur.execute("TRUNCATE TABLE links, chunks, documents RESTART IDENTITY CASCADE")

            for d in DOCS:
                did = _doc_id(d["source_url"])
                letter = d["source_url"].rsplit("-", 1)[-1].split(".")[0]  # 'a' / 'b' / 'c'
                doc_id_by_letter[letter] = did
                cur.execute(
                    """
                    INSERT INTO documents
                        (doc_id, source_url, source_type, title, topic_path,
                         reference_number, committee, revision, last_updated, raw_byte_size, meta)
                    VALUES
                        (%(doc_id)s, %(source_url)s, %(source_type)s, %(title)s, %(topic_path)s,
                         %(reference_number)s, %(committee)s, %(revision)s, %(last_updated)s,
                         %(raw_byte_size)s, %(meta)s)
                    """,
                    {
                        "doc_id": did,
                        "source_url": d["source_url"],
                        "source_type": d["source_type"],
                        "title": d["title"],
                        "topic_path": d["topic_path"],
                        "reference_number": d["reference_number"],
                        "committee": d["committee"],
                        "revision": d["revision"],
                        "last_updated": d["last_updated"],
                        "raw_byte_size": 1000,
                        "meta": json.dumps({}),
                    },
                )

            for chunk_seed, (letter, idx, text, heading) in enumerate(CHUNKS, start=1):
                did = doc_id_by_letter[letter]
                cid = _chunk_id(did, idx, text)
                chunk_id_by_letter_idx[(letter, idx)] = cid
                chunk_meta[cid] = {"letter": letter, "idx": idx, "text": text, "doc_id": did}
                emb = _deterministic_embedding(chunk_seed)
                cur.execute(
                    """
                    INSERT INTO chunks
                        (chunk_id, doc_id, chunk_index, text, heading_path, token_count, embedding)
                    VALUES
                        (%(chunk_id)s, %(doc_id)s, %(chunk_index)s, %(text)s,
                         %(heading_path)s, %(token_count)s, %(embedding)s)
                    """,
                    {
                        "chunk_id": cid,
                        "doc_id": did,
                        "chunk_index": idx,
                        "text": text,
                        "heading_path": heading,
                        "token_count": len(text.split()),
                        "embedding": emb,
                    },
                )

            # Two resolved links: CHMP doc-a → PRAC doc-b (hyperlink), and a
            # reference_number link CHMP doc-a → doc-b via EMA/PRAC/00002/2024.
            a_id, b_id = doc_id_by_letter["a"], doc_id_by_letter["b"]
            cur.execute(
                "INSERT INTO links (src_doc_id, tgt_url, tgt_doc_id, link_type, anchor, chunk_id) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (a_id, "https://test.local/ema/prac/doc-b.pdf", b_id, "hyperlink", "see also",
                 chunk_id_by_letter_idx[("a", 3)]),
            )
            cur.execute(
                "INSERT INTO links (src_doc_id, tgt_url, tgt_doc_id, link_type, anchor, chunk_id) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (a_id, "EMA/PRAC/00002/2024", b_id, "reference_number", None,
                 chunk_id_by_letter_idx[("a", 2)]),
            )
        conn.commit()

    return {
        "doc_ids": doc_id_by_letter,
        "chunk_ids": chunk_id_by_letter_idx,
        "chunk_meta": chunk_meta,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_test_pool():
    """Dedicated pool against PG_DSN_TEST; closed at session end."""
    load_dotenv(os.path.expanduser("~/.myenvs/ema_nlp.env"), override=False)
    dsn = os.getenv("PG_DSN_TEST")
    if not dsn:
        pytest.skip("PG_DSN_TEST not set — skipping retrieve_pg integration tests")
    try:
        pool = ConnectionPool(
            conninfo=dsn,
            min_size=1,
            max_size=4,
            timeout=10.0,
            configure=lambda c: register_vector(c),
            open=True,
        )
    except Exception as exc:
        pytest.skip(f"Test DB unreachable at {dsn}: {exc}")
    try:
        yield pool
    finally:
        pool.close()


@pytest.fixture(scope="session")
def seeded_corpus(pg_test_pool):
    return _seed_corpus(pg_test_pool)


@pytest.fixture()
def patch_query_embedding(monkeypatch, seeded_corpus):
    """Return a helper that points ``_query_embedding`` at the embedding of
    a specific (letter, idx) chunk. Reset to a no-op after each test."""

    def _set_to(letter: str, idx: int) -> None:
        # Re-derive the seed used during _seed_corpus (1-based enumerate).
        seed = next(
            i + 1
            for i, (l, j, _t, _h) in enumerate(CHUNKS)
            if l == letter and j == idx
        )
        vec = _deterministic_embedding(seed)
        # Patch the BGE-dependent path so retrieval doesn't need the model.
        monkeypatch.setattr(rp, "_query_embedding", lambda _q: vec.tolist())

    return _set_to


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_seeded_counts(seeded_corpus, pg_test_pool):
    """Fixture sanity — counts as expected after seed."""
    with pg_test_pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM documents")
        assert cur.fetchone()[0] == 3
        cur.execute("SELECT count(*) FROM chunks")
        assert cur.fetchone()[0] == 10
        cur.execute("SELECT count(*) FROM links")
        assert cur.fetchone()[0] == 2


def test_dense_top_k_returns_self_first(
    pg_test_pool, seeded_corpus, patch_query_embedding
):
    """Dense kNN: when the query vector equals a chunk's vector, that chunk
    must rank first."""
    patch_query_embedding("c", 1)  # ICH M7 chunk
    cfg = RetrievalConfigPG(mode="dense", k=5)
    results = retrieve_dense_pg("ICH M7", cfg, pool=pg_test_pool)

    assert len(results) == 5
    top_chunk_id, top_score, top_meta = results[0]
    expected_cid = seeded_corpus["chunk_ids"][("c", 1)]
    assert top_chunk_id == expected_cid
    assert top_score == pytest.approx(1.0, abs=1e-4)
    assert "ICH M7" in top_meta["text"]


def test_bm25_returns_keyword_hit(pg_test_pool, seeded_corpus):
    """BM25 finds the chunk containing a unique keyword."""
    cfg = RetrievalConfigPG(mode="bm25", k=5)
    results = retrieve_bm25_pg("psmf assessment", cfg, pool=pg_test_pool)
    assert results, "BM25 should return at least one hit for 'psmf assessment'"
    top_chunk_id, top_score, top_meta = results[0]
    expected_cid = seeded_corpus["chunk_ids"][("b", 0)]
    assert top_chunk_id == expected_cid
    assert top_score > 0
    assert "PSMF" in top_meta["text"] or "psmf" in top_meta["text"].lower()


def test_hybrid_rrf_combines_dense_and_bm25(
    pg_test_pool, seeded_corpus, patch_query_embedding
):
    """Hybrid mode returns at most k results, drawn from dense ∪ bm25."""
    patch_query_embedding("b", 0)  # dense target = PSMF chunk
    cfg = RetrievalConfigPG(mode="hybrid", k=5)
    results = retrieve_hybrid_pg("psmf assessment", cfg, pool=pg_test_pool)

    assert 0 < len(results) <= 5
    chunk_ids = {r[0] for r in results}
    # The PSMF chunk must appear (both dense + BM25 strongly favour it).
    expected_cid = seeded_corpus["chunk_ids"][("b", 0)]
    assert expected_cid in chunk_ids
    # Scores are RRF, so always positive.
    assert all(score > 0 for _, score, _ in results)


def test_prefilter_committee_restricts_to_chmp(
    pg_test_pool, seeded_corpus, patch_query_embedding
):
    """committee=['CHMP'] prefilter: every returned chunk must come from a
    CHMP document (acceptance criterion for NARR-024 / NARR-016)."""
    patch_query_embedding("b", 0)  # would otherwise return PRAC chunk
    cfg = RetrievalConfigPG(
        mode="dense",
        k=10,
        prefilter=PrefilterConfig(committee=["CHMP"]),
    )
    results = retrieve_dense_pg("psmf", cfg, pool=pg_test_pool)
    assert results, "expected CHMP chunks to be returned"
    for _cid, _score, meta in results:
        assert meta["committee"] == "CHMP", (
            f"prefilter leaked a non-CHMP chunk: committee={meta['committee']!r}"
        )


def test_prefilter_date_range_restricts_to_window(
    pg_test_pool, seeded_corpus, patch_query_embedding
):
    """date_range prefilter: only docs whose last_updated is in window."""
    patch_query_embedding("c", 1)  # HTML doc last_updated 2023-12-05
    cfg = RetrievalConfigPG(
        mode="dense",
        k=10,
        prefilter=PrefilterConfig(
            date_range=(
                datetime(2024, 1, 1, tzinfo=UTC),
                datetime(2024, 12, 31, tzinfo=UTC),
            ),
        ),
    )
    results = retrieve_dense_pg("ICH M7", cfg, pool=pg_test_pool)
    # The HTML doc (2023-12-05) is excluded; only CHMP + PRAC are eligible.
    # row_to_result ISO-encodes last_updated to a string for JSON safety.
    assert results, "expected at least one chunk in the date window"
    for _cid, _score, meta in results:
        last = datetime.fromisoformat(meta["last_updated"])
        assert datetime(2024, 1, 1, tzinfo=UTC) <= last <= datetime(2024, 12, 31, tzinfo=UTC)


def test_auto_traversal_expands_via_links(
    pg_test_pool, seeded_corpus, patch_query_embedding
):
    """When traversal.mode='auto' and the seed is a CHMP chunk, the link
    expansion must add a representative chunk from the PRAC neighbour."""
    patch_query_embedding("a", 0)  # CHMP chunk; doc-a links to doc-b
    cfg = RetrievalConfigPG(
        mode="dense",
        k=2,
        traversal=TraversalConfig(
            mode="auto", max_hops=1, link_types=["hyperlink", "reference_number"]
        ),
    )
    results = retrieve_with_config_pg(cfg, "any query", pool=pg_test_pool)

    chunk_ids = [r[0] for r in results]
    # Seed (chunk_id for ('a', 0)) must be first.
    assert chunk_ids[0] == seeded_corpus["chunk_ids"][("a", 0)]
    # Expansion must include a doc-b chunk (any chunk_index).
    b_doc_id = seeded_corpus["doc_ids"]["b"]
    b_letter_chunks = {
        cid for (letter, _idx), cid in seeded_corpus["chunk_ids"].items() if letter == "b"
    }
    expanded = set(chunk_ids[2:])  # seeds were 2 (k=2)
    assert b_letter_chunks & expanded, (
        f"expected at least one PRAC neighbour in expansion, got {expanded}"
    )
    # Expansion chunks must belong to doc-b.
    for _cid, _score, meta in results[2:]:
        assert meta["doc_id"] == b_doc_id


def test_auto_traversal_max_hops_zero_is_noop(
    pg_test_pool, seeded_corpus, patch_query_embedding
):
    """max_hops=0 returns exactly the seeds, no expansion."""
    patch_query_embedding("a", 0)
    cfg = RetrievalConfigPG(
        mode="dense",
        k=3,
        traversal=TraversalConfig(mode="auto", max_hops=0),
    )
    results = retrieve_with_config_pg(cfg, "any query", pool=pg_test_pool)
    assert len(results) == 3


def test_retrieve_with_config_dispatches_on_mode(
    pg_test_pool, seeded_corpus, patch_query_embedding
):
    """Dispatcher must route to the right retriever per config.mode."""
    patch_query_embedding("c", 1)
    cfg_dense = RetrievalConfigPG(mode="dense", k=3)
    cfg_bm25 = RetrievalConfigPG(mode="bm25", k=3)
    cfg_hybrid = RetrievalConfigPG(mode="hybrid", k=3)

    res_dense = retrieve_with_config_pg(cfg_dense, "ICH M7", pool=pg_test_pool)
    res_bm25 = retrieve_with_config_pg(cfg_bm25, "ICH M7", pool=pg_test_pool)
    res_hybrid = retrieve_with_config_pg(cfg_hybrid, "ICH M7", pool=pg_test_pool)

    assert res_dense and res_bm25 and res_hybrid
    assert all(len(r) <= 3 for r in [res_dense, res_bm25, res_hybrid])
