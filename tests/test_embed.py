"""Tests for harness/embed.py — index build, persist, reload, retrieval."""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from llama_index.core.embeddings import BaseEmbedding

from corpus.extractors.html_extractor import _qa_id
from corpus.models import QARecord
from harness.embed import (
    EMBED_DIM,
    _build_nodes,
    _load_records,
    build_index,
    dense_retrieve,
    follow_cross_refs,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rec(
    question: str,
    answer: str = "The answer is yes.",
    source_url: str = "https://ema.europa.eu/qa",
    source_type: str = "html_accordion",
    topic_path: str = "/human-regulatory/safety",
    cross_refs: list | None = None,
) -> QARecord:
    return QARecord(
        qa_id=_qa_id(source_url, question),
        question=question,
        answer=answer,
        source_url=source_url,
        source_type=source_type,  # type: ignore[arg-type]
        source_title="Test",
        topic_path=topic_path,
        cross_refs=cross_refs or [],
        extraction_confidence="high",
    )


def _write_corpus(path: Path, records: list[QARecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for r in records:
            fh.write(r.to_json() + "\n")


class _FakeEmbedModel(BaseEmbedding):
    """Deterministic fake embedder: each unique text gets a stable random unit vector."""

    _cache: dict[str, list[float]] = {}

    def _embed(self, text: str) -> list[float]:
        if text not in self._cache:
            rng = random.Random(hash(text) & 0xFFFFFFFF)
            vec = [rng.gauss(0, 1) for _ in range(EMBED_DIM)]
            norm = sum(v ** 2 for v in vec) ** 0.5
            self._cache[text] = [v / norm for v in vec]
        return self._cache[text]

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._embed(text)

    def _get_query_embedding(self, text: str) -> list[float]:
        return self._embed(text)

    async def _aget_query_embedding(self, text: str) -> list[float]:
        return self._embed(text)

    def get_text_embedding_batch(self, texts: list[str], **_) -> list[list[float]]:
        return [self._embed(t) for t in texts]


# ---------------------------------------------------------------------------
# _load_records
# ---------------------------------------------------------------------------

def test_load_records(tmp_path: Path) -> None:
    records = [_rec(f"Question {i}?", source_url=f"https://ema.europa.eu/{i}") for i in range(5)]
    corpus = tmp_path / "corpus.jsonl"
    _write_corpus(corpus, records)
    loaded = _load_records(corpus)
    assert len(loaded) == 5
    assert all(isinstance(r, QARecord) for r in loaded)


# ---------------------------------------------------------------------------
# _build_nodes
# ---------------------------------------------------------------------------

def test_build_nodes_count() -> None:
    records = [_rec(f"Q{i}?", source_url=f"https://ema.europa.eu/{i}") for i in range(4)]
    nodes = _build_nodes(records)
    assert len(nodes) == 4


def test_build_nodes_text_format() -> None:
    rec = _rec("What is the AI?", answer="The acceptable intake is 1.5 μg/day.")
    nodes = _build_nodes([rec])
    assert "Q: What is the AI?" in nodes[0].text
    assert "A: The acceptable intake" in nodes[0].text


def test_build_nodes_metadata() -> None:
    rec = _rec("What is the AI?", topic_path="/human-regulatory/safety")
    nodes = _build_nodes([rec])
    assert nodes[0].metadata["topic_path"] == "/human-regulatory/safety"
    assert nodes[0].metadata["qa_id"] == rec.qa_id
    assert nodes[0].id_ == rec.qa_id


def test_build_nodes_cross_refs_in_metadata() -> None:
    r1 = _rec("What is the AI?", source_url="https://ema.europa.eu/1")
    r2 = _rec("What is the LoQ?", source_url="https://ema.europa.eu/2", cross_refs=[r1.qa_id])
    nodes = _build_nodes([r1, r2])
    node_map = {n.id_: n for n in nodes}
    assert r1.qa_id in node_map[r2.qa_id].metadata["cross_refs"]


# ---------------------------------------------------------------------------
# build_index + dense_retrieve (patched embed model)
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_index(tmp_path: Path):
    records = [
        _rec("What is the acceptable intake for nitrosamines?",
             answer="1.5 μg/day.", source_url="https://ema.europa.eu/1"),
        _rec("What is the limit of quantification?",
             answer="Lowest measurable concentration.", source_url="https://ema.europa.eu/2"),
        _rec("How are Type IA variations submitted?",
             answer="Via the EMA portal.", source_url="https://ema.europa.eu/3"),
        _rec("What is a Type II variation?",
             answer="A major change to the marketing authorisation.",
             source_url="https://ema.europa.eu/4"),
        _rec("What is worksharing?",
             answer="A procedure for simultaneous variations.",
             source_url="https://ema.europa.eu/5"),
    ]
    corpus = tmp_path / "corpus.jsonl"
    _write_corpus(corpus, records)

    fake_embed = _FakeEmbedModel()
    idx = build_index(corpus, tmp_path / "index", force=True, embed_model=fake_embed)

    return idx, records, fake_embed, tmp_path


def test_dense_retrieve_returns_results(fake_index) -> None:
    idx, _, fake_embed, _ = fake_index
    results = dense_retrieve(idx, "nitrosamine acceptable intake", k=5, embed_model=fake_embed)
    assert len(results) > 0
    assert all(isinstance(qa_id, str) for qa_id, _ in results)
    assert all(isinstance(score, float) for _, score in results)


def test_dense_retrieve_respects_k(fake_index) -> None:
    idx, _, fake_embed, _ = fake_index
    results = dense_retrieve(idx, "acceptable intake", k=2, embed_model=fake_embed)
    assert len(results) <= 2


def test_index_persisted_to_disk(fake_index) -> None:
    _, _, _, tmp_path = fake_index
    assert (tmp_path / "index" / "docstore.json").exists()
    assert (tmp_path / "index" / "faiss.index").exists()


def test_follow_cross_refs(tmp_path: Path) -> None:
    r1 = _rec("What is the AI?", source_url="https://ema.europa.eu/1")
    r2 = _rec("What is the LoQ?", source_url="https://ema.europa.eu/2", cross_refs=[r1.qa_id])
    corpus = tmp_path / "corpus.jsonl"
    _write_corpus(corpus, [r1, r2])

    fake_embed = _FakeEmbedModel()
    idx = build_index(corpus, tmp_path / "index", force=True, embed_model=fake_embed)

    related = follow_cross_refs(idx, r2.qa_id)
    assert len(related) == 1
    assert related[0].metadata["qa_id"] == r1.qa_id


def test_follow_cross_refs_empty_for_no_refs(fake_index) -> None:
    idx, records, _, _ = fake_index
    related = follow_cross_refs(idx, records[0].qa_id)
    assert related == []


def test_known_question_retrieves_itself_top1(fake_index) -> None:
    idx, records, fake_embed, _ = fake_index
    r = records[0]
    # Querying with the exact stored node text gives identical embedding → distance 0 → top-1.
    query = f"Q: {r.question}\n\nA: {r.answer}"
    results = dense_retrieve(idx, query, k=1, embed_model=fake_embed)
    assert len(results) == 1
    assert results[0][0] == r.qa_id
