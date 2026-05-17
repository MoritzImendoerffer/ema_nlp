"""Tests for harness/retrieve.py — BM25, dense, and hybrid RRF retrieval."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
from llama_index.core.embeddings import BaseEmbedding

from corpus.extractors.html_extractor import _qa_id
from corpus.models import QARecord
from harness.embed import EMBED_DIM, build_index
from harness.retrieve import RetrievalResult, retrieve


# ---------------------------------------------------------------------------
# Shared helpers (mirror test_embed.py style)
# ---------------------------------------------------------------------------

def _rec(
    question: str,
    answer: str = "The answer is yes.",
    source_url: str = "https://ema.europa.eu/qa",
    topic_path: str = "/human-regulatory/safety",
) -> QARecord:
    return QARecord(
        qa_id=_qa_id(source_url, question),
        question=question,
        answer=answer,
        source_url=source_url,
        source_type="html_accordion",  # type: ignore[arg-type]
        source_title="Test",
        topic_path=topic_path,
        cross_refs=[],
        extraction_confidence="high",
    )


def _write_corpus(path: Path, records: list[QARecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in records:
            fh.write(r.to_json() + "\n")


# ---------------------------------------------------------------------------
# Controlled fake embedder for the exact-match test.
#
# The query "26.5 ng/day" is mapped to a unit vector in dimension 0.
# The target document (containing "26.5 ng/day") is mapped to dimension 1
# (orthogonal → cosine similarity = 0 with the query).
# All other documents are mapped to dimension 0 (identical to the query →
# cosine similarity ≈ 1), so dense retrieval ranks the target last.
# ---------------------------------------------------------------------------

class _BiasedEmbedModel(BaseEmbedding):
    """Deterministic embed model that makes exact-match documents score poorly in dense retrieval."""

    TARGET_KEYWORD: ClassVar[str] = "26.5 ng/day"

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * EMBED_DIM
        if self.TARGET_KEYWORD in text and text.startswith("Q:"):
            # Document node containing the keyword → dimension 1 (orthogonal to query)
            vec[1] = 1.0
        else:
            # Query and all other documents → dimension 0
            vec[0] = 1.0
        return vec

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._embed(text)

    def _get_query_embedding(self, text: str) -> list[float]:
        return self._embed(text)

    async def _aget_query_embedding(self, text: str) -> list[float]:
        return self._embed(text)

    def get_text_embedding_batch(self, texts: list[str], **_) -> list[list[float]]:
        return [self._embed(t) for t in texts]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TARGET_QUERY = "26.5 ng/day"

# 10 non-target records + 1 target record (11 total).
# Dense retrieval (k=5) returns the 5 non-target docs closest to the query
# and excludes the target entirely (its embedding is orthogonal to the query).
# BM25 (k=5) puts the target at rank 0 and fills remaining slots with non-targets.
# Hybrid RRF therefore recalls the target even though dense misses it.
_NON_TARGET_RECORDS = [
    _rec(f"What is EMA procedure step {i}?",
         answer=f"Step {i} involves regulatory review.",
         source_url=f"https://ema.europa.eu/proc/{i}")
    for i in range(10)
]
_TARGET_RECORD = _rec(
    "What is the acceptable intake for nitrosamines?",
    answer="The limit is 26.5 ng/day for this impurity.",
    source_url="https://ema.europa.eu/nitrosamine",
)
RECORDS = [_TARGET_RECORD] + _NON_TARGET_RECORDS

TARGET_QA_ID = _TARGET_RECORD.qa_id


@pytest.fixture()
def biased_index(tmp_path: Path):
    corpus = tmp_path / "corpus.jsonl"
    _write_corpus(corpus, RECORDS)
    embed = _BiasedEmbedModel()
    idx = build_index(corpus, tmp_path / "index", force=True, embed_model=embed)
    return idx, embed


# ---------------------------------------------------------------------------
# Dense retrieval
# ---------------------------------------------------------------------------

def test_dense_retrieve_returns_triples(biased_index) -> None:
    idx, embed = biased_index
    results = retrieve(idx, TARGET_QUERY, mode="dense", k=5, embed_model=embed)
    assert len(results) > 0
    for qa_id, score, meta in results:
        assert isinstance(qa_id, str)
        assert isinstance(score, float)
        assert "topic_path" in meta
        assert "source_url" in meta


def test_dense_retrieve_respects_k(biased_index) -> None:
    idx, embed = biased_index
    results = retrieve(idx, TARGET_QUERY, mode="dense", k=2, embed_model=embed)
    assert len(results) <= 2


def test_dense_misses_exact_match(biased_index) -> None:
    """With the biased embedder the target document is orthogonal to the query."""
    idx, embed = biased_index
    results = retrieve(idx, TARGET_QUERY, mode="dense", k=5, embed_model=embed)
    ids = [r[0] for r in results]
    # The target should NOT be rank-1 for dense (other docs are maximally similar)
    assert ids[0] != TARGET_QA_ID


# ---------------------------------------------------------------------------
# BM25 retrieval
# ---------------------------------------------------------------------------

def test_bm25_retrieve_returns_triples(biased_index) -> None:
    idx, _ = biased_index
    results = retrieve(idx, TARGET_QUERY, mode="bm25", k=5)
    assert len(results) > 0
    for qa_id, score, meta in results:
        assert isinstance(qa_id, str)
        assert isinstance(score, float)
        assert "topic_path" in meta


def test_bm25_finds_exact_match_top1(biased_index) -> None:
    """BM25 must rank the document containing '26.5 ng/day' at position 0."""
    idx, _ = biased_index
    results = retrieve(idx, TARGET_QUERY, mode="bm25", k=5)
    assert results[0][0] == TARGET_QA_ID


# ---------------------------------------------------------------------------
# Hybrid RRF retrieval
# ---------------------------------------------------------------------------

def test_hybrid_retrieve_returns_triples(biased_index) -> None:
    idx, embed = biased_index
    results = retrieve(idx, TARGET_QUERY, mode="hybrid", k=5, embed_model=embed)
    assert len(results) > 0
    for qa_id, score, meta in results:
        assert isinstance(qa_id, str)
        assert isinstance(score, float)
        assert "topic_path" in meta


def test_hybrid_outperforms_dense_on_exact_match(biased_index) -> None:
    """
    Hybrid (RRF) recalls the exact-match document that dense misses entirely.

    With 10 non-target docs and k=5:
    - Dense top-5: 5 non-target docs only (target is orthogonal to query → highest L2 distance).
    - BM25 top-5: target at rank 0 (exact keyword match) + 4 non-target docs.
    - Hybrid top-5: always includes the target (proven: its RRF score ≥ any dense-only doc).

    This is the key advantage of hybrid retrieval for exact-match regulatory figures.
    """
    idx, embed = biased_index
    k = 5

    dense_results = retrieve(idx, TARGET_QUERY, mode="dense", k=k, embed_model=embed)
    hybrid_results = retrieve(idx, TARGET_QUERY, mode="hybrid", k=k, embed_model=embed)

    dense_ids = [r[0] for r in dense_results]
    hybrid_ids = [r[0] for r in hybrid_results]

    # Dense misses the exact-match document entirely (it has 10 non-target docs to fill top-5)
    assert TARGET_QA_ID not in dense_ids, "Dense should miss the exact-match doc"
    # Hybrid recalls it
    assert TARGET_QA_ID in hybrid_ids, "Hybrid should surface the exact-match doc"


# ---------------------------------------------------------------------------
# Metadata completeness
# ---------------------------------------------------------------------------

def test_metadata_includes_required_fields(biased_index) -> None:
    idx, embed = biased_index
    for mode in ("dense", "bm25", "hybrid"):
        results = retrieve(idx, "variation submission", mode=mode, k=3, embed_model=embed)  # type: ignore[arg-type]
        for _, _, meta in results:
            assert "qa_id" in meta
            assert "topic_path" in meta
            assert "source_url" in meta
            assert "cross_refs" in meta
