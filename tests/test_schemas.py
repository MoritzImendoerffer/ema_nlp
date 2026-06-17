"""Unit tests for harness.schemas (Pydantic answer/citation/substance contracts).

Pure-Pydantic; no LlamaIndex needed. Fake node objects exercise the duck-typed
citation builder.
"""

import pytest
from pydantic import ValidationError

from harness.schemas import Citation, Claim, RegulatoryAnswer, Substance, citation_from_node


class _FakeNode:
    def __init__(self, text, metadata):
        self.text = text
        self.metadata = metadata


class _FakeNodeWithScore:
    def __init__(self, node, score):
        self.node = node
        self.score = score


def test_regulatory_answer_defaults():
    ans = RegulatoryAnswer(answer="x")
    assert ans.answer == "x"
    assert ans.claims == []
    assert ans.citations == []
    assert ans.confidence == 0.0
    assert ans.caveats == []


def test_confidence_bounds_enforced():
    with pytest.raises(ValidationError):
        RegulatoryAnswer(answer="x", confidence=1.5)
    with pytest.raises(ValidationError):
        RegulatoryAnswer(answer="x", confidence=-0.1)


def test_claim_with_citations_roundtrips_json():
    ans = RegulatoryAnswer(
        answer="The AI for NDMA is 96 ng/day.",
        claims=[
            Claim(
                text="AI for NDMA is 96 ng/day",
                citations=[Citation(source_url="https://ema.europa.eu/ndma", doc_id="d1")],
            )
        ],
        confidence=0.8,
    )
    dumped = ans.model_dump()
    assert dumped["claims"][0]["citations"][0]["source_url"] == "https://ema.europa.eu/ndma"
    # round-trips through JSON
    again = RegulatoryAnswer.model_validate_json(ans.model_dump_json())
    assert again == ans


def test_citation_from_node_with_score():
    node = _FakeNode("  The AI for NDMA is 96 ng/day.\n", {"source_url": "u", "doc_id": "d1"})
    cit = citation_from_node(_FakeNodeWithScore(node, 0.91))
    assert cit.source_url == "u"
    assert cit.doc_id == "d1"
    assert cit.score == pytest.approx(0.91)
    assert cit.quote == "The AI for NDMA is 96 ng/day."  # whitespace normalized


def test_citation_from_bare_node_reads_score_from_metadata():
    node = _FakeNode("text", {"source_url": "u", "id": "c7", "score": "0.5"})
    cit = citation_from_node(node)
    assert cit.chunk_id == "c7"
    assert cit.score == pytest.approx(0.5)


def test_citation_quote_truncated():
    node = _FakeNode("word " * 200, {"source_url": "u"})
    cit = citation_from_node(node)
    assert len(cit.quote) <= 241  # 240 + ellipsis
    assert cit.quote.endswith("…")


def test_from_nodes_collects_citations():
    nodes = [
        _FakeNodeWithScore(_FakeNode("a", {"source_url": "u1", "doc_id": "d1"}), 0.9),
        _FakeNodeWithScore(_FakeNode("b", {"source_url": "u2", "doc_id": "d2"}), 0.8),
    ]
    ans = RegulatoryAnswer.from_nodes("answer", nodes, confidence=0.7)
    assert [c.source_url for c in ans.citations] == ["u1", "u2"]
    assert ans.confidence == pytest.approx(0.7)


def test_substance_defaults():
    sub = Substance(query="NDMA")
    assert sub.found is True
    assert sub.atc == []
    assert sub.molecular_weight is None
