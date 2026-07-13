"""Unit tests for the topic-subgraph build side.

harness.indexing.subgraphs (walk query, membership collection, propose scoring)
with a fake store, and document_metadata.upsert_topic_hubs with mongomock —
including composition with the other label groups and re-build (pull) semantics.
"""

from __future__ import annotations

import mongomock
import pytest

from config import MONGO_DB
from harness.indexing.chunking import doc_id_for
from harness.indexing.document_metadata import (
    COLLECTION,
    upsert_badges,
    upsert_topic_hubs,
)
from harness.indexing.subgraphs import (
    HubCandidate,
    build_memberships,
    composition_histogram,
    invert_memberships,
    key_for_url,
    walk_members,
    walk_query,
)
from harness.retrieval.hubs import HubSpec, HubWalk

_SEED = "https://www.ema.europa.eu/en/hub-a"
_HUB = HubSpec(
    key="referral_procedures",
    seed_url=_SEED,
    status="confirmed",
    walk=HubWalk(hops=2, categories=("qa",), exclude_audience=("Veterinary",)),
)


class _FakeStore:
    def __init__(self, rows, *, seed_exists=True):
        self.rows = rows
        self.seed_exists = seed_exists
        self.calls: list[tuple[str, dict]] = []

    def structured_query(self, query, param_map=None):
        self.calls.append((query, param_map or {}))
        if "LIMIT 1" in query:  # the seed-resolution probe
            return [{"id": param_map["id"]}] if self.seed_exists else []
        return self.rows


# --- walk query --------------------------------------------------------------


def test_walk_query_qualifies_every_node_on_the_path():
    q = walk_query(2)
    assert "[:LINKS_TO*1..2]" in q
    assert "ALL(n IN nodes(p)[1..]" in q  # intermediates qualified, not just endpoints
    assert "n.category IN $cats OR n.doc_type IN $doctypes" in q  # category-OR-doc_type
    assert "coalesce(n.audience, '') IN $exclude" in q


def test_walk_query_rejects_bad_hops():
    with pytest.raises(ValueError):
        walk_query(0)


def test_walk_members_includes_seed_and_passes_qualifier():
    member = {"id": "m1", "url": "https://x/1", "title": "Doc 1", "category": "qa"}
    store = _FakeStore([member])
    members = walk_members(store, _HUB)
    assert {m["id"] for m in members} == {doc_id_for(_SEED), "m1"}
    _query, params = store.calls[-1]
    assert params["seed_id"] == doc_id_for(_SEED)
    assert params["cats"] == ["qa"] and params["exclude"] == ["Veterinary"]


def test_build_memberships_fails_loudly_on_dangling_seed():
    with pytest.raises(ValueError, match="referral_procedures"):
        build_memberships(_FakeStore([], seed_exists=False), [_HUB])


def test_invert_memberships_multi_membership():
    per_hub = {
        "a": [{"id": "1", "url": "u1"}, {"id": "2", "url": "u2"}],
        "b": [{"id": "2", "url": "u2"}],
    }
    assert invert_memberships(per_hub) == {"u1": ["a"], "u2": ["a", "b"]}


def test_composition_histogram_counts_nones():
    hist = composition_histogram([{"category": "qa"}, {"category": None}], "category")
    assert hist == {"qa": 1, "(none)": 1}


# --- propose scoring (explainable, penalty-based) -----------------------------


def test_candidate_score_weights_curated_links_double():
    c = HubCandidate(url="u", title="Referral procedures", curated_links=10, inline_links=4)
    assert c.score == 24.0 and c.penalized == ""


def test_candidate_score_penalizes_archive_and_audience():
    archive = HubCandidate(url="u", title="Archive of development of GVP",
                           curated_links=50, inline_links=26)
    live = HubCandidate(url="u", title="Good pharmacovigilance practices",
                        curated_links=10, inline_links=2)
    # the raw out-fanout trap (§2): the archive out-fans the live page but must rank below
    assert archive.score < live.score
    assert "archive/news title" in archive.penalized

    vet = HubCandidate(url="u", title="X", curated_links=10, inline_links=0,
                       audience="Veterinary")
    assert vet.score == pytest.approx(4.0) and "audience=Veterinary" in vet.penalized


def test_key_for_url_slugs_and_dedupes():
    existing = {"referral_procedures_human_medicines"}
    url = "https://www.ema.europa.eu/en/x/referral-procedures-human-medicines"
    assert key_for_url(url, set()) == "referral_procedures_human_medicines"
    assert key_for_url(url, existing) == "referral_procedures_human_medicines_2"


# --- Mongo membership stamps (mongomock) --------------------------------------


@pytest.fixture
def client():
    return mongomock.MongoClient()


def _rows(client):
    return {r["url"]: r for r in client[MONGO_DB][COLLECTION].find({})}


def test_upsert_topic_hubs_composes_with_other_label_groups(client):
    url = "https://www.ema.europa.eu/en/page"
    upsert_badges([{"url": url, "audience": "Human", "site_topic": "X"}], client=client)
    n = upsert_topic_hubs(
        {url: ["referral_procedures"]},
        hub_keys=["referral_procedures"], config_hash="abc123", client=client,
    )
    assert n == 1
    row = _rows(client)[url]  # same URL -> ONE row, both groups
    assert row["audience"] == "Human"
    assert row["topic_hubs"] == ["referral_procedures"]
    assert row["provenance"]["topic_hubs"]["source"] == "hub_walk"
    assert row["provenance"]["topic_hubs"]["config_hash"] == "abc123"
    assert "badges" in row["provenance"]


def test_rebuild_clears_lost_membership_but_keeps_other_hubs(client):
    u1, u2 = "https://x/1", "https://x/2"
    upsert_topic_hubs({u1: ["a"], u2: ["a", "b"]}, hub_keys=["a", "b"],
                      config_hash="h1", client=client)
    # rebuild of hub "a" only: u1 lost membership, u2 keeps its "b" stamp untouched
    upsert_topic_hubs({u2: ["a"]}, hub_keys=["a"], config_hash="h2", client=client)
    rows = _rows(client)
    assert rows[u1]["topic_hubs"] == []
    assert set(rows[u2]["topic_hubs"]) == {"a", "b"}  # $addToSet — order unspecified
    assert rows[u2]["provenance"]["topic_hubs"]["config_hash"] == "h2"


def test_upsert_rejects_membership_outside_declared_hub_keys(client):
    with pytest.raises(ValueError, match="not in this build's hub_keys"):
        upsert_topic_hubs({"https://x/1": ["a", "rogue"]}, hub_keys=["a"],
                          config_hash="h", client=client)
