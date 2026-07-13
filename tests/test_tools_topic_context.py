"""Unit tests for the ``topic_context`` tool (fake reader — no Neo4j, no LLM).

Covers the §4.4 guardrails of docs/next/topic_subgraphs.md: pageable map with
an honest total + truncated flag, detail-page grouping (revisions don't read as
separate items), query ranking, hub resolution precedence (explicit key >
document membership, embedding pick on multi-membership), and the budgeted
chunks mode feeding the shared capture sink with stamped provenance.
"""

from __future__ import annotations

from harness.retrieval.hubs import HubsConfig, HubSpec, HubWalk
from harness.retrieval.subgraphs import SubgraphPolicy
from harness.tools import get_tool
from harness.tools.search import capture_search_nodes
from harness.tools.topic_context import group_members, render_map

_WALK = HubWalk(categories=("qa",))
_HUBS = HubsConfig(
    name="test",
    hubs=[
        HubSpec(key="referral", seed_url="https://ema/hub-referral", status="confirmed",
                walk=_WALK),
        HubSpec(key="gvp", seed_url="https://ema/hub-gvp", status="confirmed", walk=_WALK),
    ],
)

_MEMBERS = [
    {"id": "h1", "url": "https://ema/detail-1", "title": "Article 31 referrals",
     "category": "qa", "doc_type": None, "reference_number": None, "revision": None,
     "source_type": "html", "parent_id": None},
    {"id": "p1", "url": "https://ema/doc-1.pdf", "title": "Q&A Article 31 Rev. 4",
     "category": "qa", "doc_type": "medicine-qa", "reference_number": "EMA/1",
     "revision": None, "source_type": "pdf", "parent_id": "h1"},
    {"id": "p2", "url": "https://ema/doc-2.pdf", "title": "Q&A Article 31 Rev. 3",
     "category": "qa", "doc_type": "medicine-qa", "reference_number": "EMA/1",
     "revision": "3", "source_type": "pdf", "parent_id": "h1"},
    {"id": "h2", "url": "https://ema/detail-2", "title": "Article 30 referrals",
     "category": "qa", "doc_type": None, "reference_number": None, "revision": None,
     "source_type": "html", "parent_id": None},
]


class _FakeReader:
    def __init__(self, members=None, memberships=None, scores=None, chunks=None):
        self._members = members if members is not None else list(_MEMBERS)
        self._memberships = memberships or {}
        self._scores = scores or {}
        self._chunks = chunks or []

    def query_embedding(self, query):
        return [0.1]

    def members(self, key):
        return list(self._members)

    def memberships(self, probe):
        return list(self._memberships.get(probe, []))

    def member_scores(self, key, qvec):
        return dict(self._scores)

    def doc_scores(self, doc_ids, qvec):
        return {d: self._scores.get(d, 0.0) for d in doc_ids}

    def best_chunks(self, key, qvec, *, limit):
        return list(self._chunks)[:limit]


def _tool(reader, policy=None):
    return get_tool("topic_context", reader=reader, hubs=_HUBS,
                    subgraph=policy or SubgraphPolicy())


# --- grouping + rendering -----------------------------------------------------


def test_group_members_nests_pdfs_under_their_detail_page():
    groups = group_members(_MEMBERS)
    by_head = {g["head"]["id"]: g for g in groups}
    assert set(by_head) == {"h1", "h2"}
    # both revisions kept (title-sorted): Rev. 3 before Rev. 4
    assert [c["id"] for c in by_head["h1"]["children"]] == ["p2", "p1"]


def test_render_map_header_is_honest():
    groups = group_members(_MEMBERS)
    out = render_map(groups, key="referral", page=1, page_size=1, total_members=4)
    assert "4 documents in 2 groups" in out
    assert "page 1/2" in out and "truncated=true" in out
    assert "page=2" in out  # tells the agent how to continue
    out2 = render_map(groups, key="referral", page=2, page_size=1, total_members=4)
    assert "truncated=false" in out2
    assert "Article" in out2


def test_render_map_out_of_range_page():
    groups = group_members(_MEMBERS)
    out = render_map(groups, key="referral", page=9, page_size=25, total_members=4)
    assert "out of range" in out and "1..1" in out


def test_revision_falls_back_to_title_parse():
    tool = _tool(_FakeReader())
    out = tool.fn(topic="referral")
    assert "rev 4" in out  # parsed from "Rev. 4" in the title (no stamped revision)
    assert "rev 3" in out  # stamped revision preferred


# --- resolution precedence ------------------------------------------------------


def test_explicit_hub_key_wins():
    out = _tool(_FakeReader()).fn(topic="referral", query="")
    assert "[topic: referral" in out


def test_unknown_topic_lists_available_hubs():
    out = _tool(_FakeReader()).fn(topic="https://ema/unknown-doc")
    assert "neither a known topic key" in out
    assert "referral" in out and "gvp" in out


def test_url_resolves_via_single_membership():
    reader = _FakeReader(memberships={"https://ema/doc-1.pdf": ["referral"]})
    out = _tool(reader).fn(topic="https://ema/doc-1.pdf")
    assert "resolved from document membership: referral" in out
    assert "[topic: referral" in out


def test_multi_membership_picked_by_query_match_on_seed_pages():
    from harness.indexing.chunking import doc_id_for

    reader = _FakeReader(
        memberships={"https://ema/doc-1.pdf": ["referral", "gvp"]},
        scores={doc_id_for("https://ema/hub-gvp"): 0.9,
                doc_id_for("https://ema/hub-referral"): 0.2},
    )
    out = _tool(reader).fn(topic="https://ema/doc-1.pdf", query="pharmacovigilance modules")
    assert "picked 'gvp'" in out
    assert "[topic: gvp" in out


def test_multi_membership_without_query_is_deterministic():
    reader = _FakeReader(memberships={"https://ema/doc-1.pdf": ["referral", "gvp"]})
    out = _tool(reader).fn(topic="https://ema/doc-1.pdf")
    assert "picked 'gvp'" in out  # alphabetical fallback


def test_unbuilt_topic_says_so():
    out = _tool(_FakeReader(members=[])).fn(topic="referral")
    assert "no built subgraph" in out


# --- query ranking ---------------------------------------------------------------


def test_query_ranks_groups_by_best_member_score():
    reader = _FakeReader(scores={"h2": 0.9, "h1": 0.1, "p1": 0.2, "p2": 0.1})
    out = _tool(reader).fn(topic="referral", query="article 30")
    assert out.index("Article 30") < out.index("Article 31")
    # child score can carry its group: p1 outranks h1's own score
    reader2 = _FakeReader(scores={"h2": 0.15, "h1": 0.1, "p1": 0.9})
    out2 = _tool(reader2).fn(topic="referral", query="article 31")
    assert out2.index("Article 31") < out2.index("Article 30")


# --- budgeted chunks mode ---------------------------------------------------------


_CHUNK_ROWS = [
    {"id": "p1", "url": "https://ema/doc-1.pdf", "title": "Q&A Article 31 Rev. 4",
     "category": "qa", "doc_type": "medicine-qa", "reference_number": "EMA/1",
     "source_type": "pdf",
     "best": {"id": "c1", "text": "fees apply regardless of initiator " * 20,
              "score": 0.8, "parent": {"id": "par1", "text": "PARENT " * 40}}},
    {"id": "h2", "url": "https://ema/detail-2", "title": "Article 30 referrals",
     "category": "qa", "doc_type": None, "reference_number": None,
     "source_type": "html",
     "best": {"id": "c2", "text": "divergent SmPCs trigger Article 30 " * 20,
              "score": 0.6, "parent": None}},
]


def test_chunks_mode_appends_budgeted_context_and_sinks_nodes():
    policy = SubgraphPolicy(context="chunks", max_tokens=4000, page_size=25)
    tool = _tool(_FakeReader(chunks=_CHUNK_ROWS), policy)
    with capture_search_nodes() as sink:
        out = tool.fn(topic="referral", query="fees")
    assert "topic context: best passages" in out
    assert "PARENT" in out  # small-to-big: the parent text is returned
    assert len(sink) == 2
    meta = sink[0].node.metadata
    assert meta["retrieval_origin"] == "topic_subgraph"
    assert meta["topic_hub"] == "referral"
    assert sink[0].node.node_id == "par1"  # parent merge
    assert meta["matched_chunk"] == "c1"


def test_chunks_mode_respects_token_budget():
    policy = SubgraphPolicy(context="chunks", max_tokens=60, page_size=25)
    tool = _tool(_FakeReader(chunks=_CHUNK_ROWS), policy)
    with capture_search_nodes() as sink:
        out = tool.fn(topic="referral", query="fees")
    assert len(sink) == 1  # the second chunk would blow the budget
    assert "best passages from 1 of 2 members" in out


def test_chunks_mode_without_query_returns_map_only():
    policy = SubgraphPolicy(context="chunks")
    tool = _tool(_FakeReader(chunks=_CHUNK_ROWS), policy)
    with capture_search_nodes() as sink:
        out = tool.fn(topic="referral")
    assert "returning the map only" in out
    assert sink == []


def test_chunks_mode_only_on_first_page():
    policy = SubgraphPolicy(context="chunks", page_size=1)
    tool = _tool(_FakeReader(chunks=_CHUNK_ROWS), policy)
    with capture_search_nodes() as sink:
        out = tool.fn(topic="referral", query="fees", page=2)
    assert "topic context: best passages" not in out
    assert sink == []


# --- registry + builder wiring ------------------------------------------------------


def test_registered_and_description_names_confirmed_hubs():
    tool = _tool(_FakeReader())
    assert tool.metadata.name == "topic_context"
    assert "referral" in tool.metadata.description


def test_builder_requires_reader_or_capable_retriever():
    import pytest

    with pytest.raises(ValueError, match="reader"):
        get_tool("topic_context", retriever=object(), hubs=_HUBS)
