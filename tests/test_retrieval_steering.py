"""Unit tests for harness.retrieval.steering (pure category-steering primitives).

Offline: plain NodeWithScore fixtures, no store, no LLM.
"""

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from harness.retrieval.doc_categories import CATEGORIES
from harness.retrieval.steering import (
    node_category,
    parse_categories,
    sort_by_category_priority,
    stratify_by_category,
    validate_quota,
)


def _node(category: str, score: float, text: str = "x") -> NodeWithScore:
    return NodeWithScore(
        node=TextNode(text=text, metadata={"category": category, "source_url": "u"}),
        score=score,
    )


# --- node_category -----------------------------------------------------------


def test_node_category_prefers_stamped_metadata():
    assert node_category(_node("qa", 0.9)) == "qa"


def test_node_category_classifies_when_unstamped():
    n = NodeWithScore(
        node=TextNode(
            text="x",
            metadata={"source_url": "https://ema.europa.eu/documents/scientific-guideline/x"},
        ),
        score=0.5,
    )
    assert node_category(n) == "scientific_guideline"


def test_node_category_unknown_is_other():
    assert node_category(NodeWithScore(node=TextNode(text="x"), score=0.1)) == "other"


# --- parse_categories --------------------------------------------------------


def test_parse_categories_comma_separated():
    assert parse_categories("qa, epar") == ["qa", "epar"]


def test_parse_categories_empty():
    assert parse_categories("") == []
    assert parse_categories("  ,  ") == []


def test_parse_categories_unknown_raises_with_vocabulary():
    with pytest.raises(ValueError) as exc:
        parse_categories("guidelines")
    assert "scientific_guideline" in str(exc.value)  # names the valid vocabulary


# --- sort_by_category_priority -------------------------------------------------


def test_sort_priority_floats_preferred_categories_stably():
    nodes = [_node("epar", 0.9), _node("qa", 0.8), _node("epar", 0.7), _node("qa", 0.6)]
    ordered = sort_by_category_priority(nodes, ["qa"])
    assert [node_category(n) for n in ordered] == ["qa", "qa", "epar", "epar"]
    # ties keep score order
    assert [n.score for n in ordered] == [0.8, 0.6, 0.9, 0.7]


def test_sort_priority_empty_priority_is_identity():
    nodes = [_node("epar", 0.9), _node("qa", 0.8)]
    assert sort_by_category_priority(nodes, []) == nodes


# --- stratify_by_category ------------------------------------------------------


def test_stratify_guarantees_quota_slots():
    # 4 epar hits outscore the guideline/qa hits; k=4 with quotas must still
    # include the best guideline and the best qa, preserving score order.
    nodes = [
        _node("epar", 0.9),
        _node("epar", 0.8),
        _node("epar", 0.7),
        _node("epar", 0.6),
        _node("scientific_guideline", 0.5),
        _node("qa", 0.4),
        _node("scientific_guideline", 0.3),
    ]
    out = stratify_by_category(nodes, {"scientific_guideline": 1, "qa": 1}, 4)
    cats = [node_category(n) for n in out]
    assert cats == ["epar", "epar", "scientific_guideline", "qa"]
    assert [n.score for n in out] == [0.9, 0.8, 0.5, 0.4]


def test_stratify_quota_is_guarantee_not_requirement():
    # no qa nodes in the pool: the slot goes back to the best remaining nodes
    nodes = [_node("epar", 0.9), _node("epar", 0.8), _node("epar", 0.7)]
    out = stratify_by_category(nodes, {"qa": 2}, 2)
    assert [n.score for n in out] == [0.9, 0.8]


def test_stratify_no_quota_or_small_pool_is_topk():
    nodes = [_node("epar", 0.9), _node("qa", 0.8)]
    assert stratify_by_category(nodes, {}, 1) == nodes[:1]
    assert stratify_by_category(nodes, {"qa": 1}, 5) == nodes  # pool <= k untouched


def test_stratify_k_zero():
    assert stratify_by_category([_node("qa", 0.9)], {"qa": 1}, 0) == []


# --- validate_quota ------------------------------------------------------------


def test_validate_quota_accepts_known_categories():
    validate_quota({c: 1 for c in CATEGORIES if c != "other"}, k=10)


def test_validate_quota_rejects_unknown_category():
    with pytest.raises(ValueError, match="unknown"):
        validate_quota({"guidelines": 2})


def test_validate_quota_rejects_nonpositive():
    with pytest.raises(ValueError, match=">= 1"):
        validate_quota({"qa": 0})


def test_validate_quota_rejects_total_over_k():
    with pytest.raises(ValueError, match="exceeds"):
        validate_quota({"qa": 6, "epar": 5}, k=10)
