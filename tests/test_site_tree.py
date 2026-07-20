"""harness.indexing.site_tree — tree records + layered layout (pure, offline)."""

from __future__ import annotations

from harness.indexing.site_tree import (
    SEC_PREFIX,
    build_tree,
    derive_tree_records,
    layered_positions,
)


def _doc(id: str, topic_path: str, source_type: str, title: str | None = None) -> dict:
    return {
        "id": id,
        "title": title or f"Title {id}",
        "category": "qa",
        "doc_type": "",
        "audience": "",
        "site_topic": "",
        "source_url": f"https://www.ema.europa.eu/x/{id}",
        "topic_path": topic_path,
        "source_type": source_type,
    }


def _site():
    """Two-level site: a page occupying /medicines, a deep page under it,
    a PDF linked from the deep page, and an orphan PDF in a bucket."""
    return [
        _doc("sec-med", "/en/medicines/", "html"),
        _doc("page1", "/en/medicines/human/page1/", "html"),
        _doc("pdf-linked", "/en/documents/report/", "pdf"),
        _doc("pdf-orphan", "/en/documents/report/", "pdf"),
    ]


LINKS = [("page1", "pdf-linked")]


def test_records_every_doc_exactly_once_with_expected_parents():
    records = derive_tree_records(_site(), LINKS)
    assert set(records) == {"sec-med", "page1", "pdf-linked", "pdf-orphan"}

    # doc occupying /medicines: parented by the synthetic root → parent_id ""
    assert records["sec-med"].parent_id == ""
    assert records["sec-med"].depth == 1
    assert records["sec-med"].path == "medicines"

    # deep page: under §medicines/human (synthetic) → parent_id "", but the
    # doc-backed /medicines page is its ancestor
    assert records["page1"].parent_id == ""
    assert records["page1"].path == "medicines/human/page1"
    assert records["page1"].ancestor_ids == ("sec-med",)

    # linked PDF: parented by the linking page, inherits its path
    assert records["pdf-linked"].parent_id == "page1"
    assert records["pdf-linked"].path == "medicines/human/page1"
    assert records["pdf-linked"].depth == records["page1"].depth + 1
    assert records["pdf-linked"].ancestor_ids == ("sec-med", "page1")

    # orphan PDF: bucket fallback, no doc-backed ancestors
    assert records["pdf-orphan"].parent_id == ""
    assert records["pdf-orphan"].path == "documents/report"
    assert records["pdf-orphan"].ancestor_ids == ()


def test_depths_are_tree_distances_from_root():
    records = derive_tree_records(_site(), LINKS)
    # root(0) → sec-med occupying /medicines
    assert records["sec-med"].depth == 1
    # root → sec-med → §medicines/human → page1
    assert records["page1"].depth == 3
    # root → §documents → pdf-orphan? bucket is documents/report → depth 3
    assert records["pdf-orphan"].depth == 3


def test_ancestor_ids_are_doc_backed_root_to_nearest():
    records = derive_tree_records(_site(), LINKS)
    for rec in records.values():
        assert all(not a.startswith(SEC_PREFIX) for a in rec.ancestor_ids)
    assert records["pdf-linked"].ancestor_ids[0] == "sec-med"  # root-most first
    assert records["pdf-linked"].ancestor_ids[-1] == "page1"  # nearest last


def test_derive_is_deterministic():
    assert derive_tree_records(_site(), LINKS) == derive_tree_records(_site(), LINKS)


def test_layered_positions_complete_deterministic_and_depth_monotone():
    nodes = _site()
    sections, children, _ = build_tree(nodes, LINKS)
    all_nodes = nodes + sections
    pos1 = layered_positions(all_nodes, children)
    pos2 = layered_positions(all_nodes, children)
    assert pos1 == pos2
    assert set(pos1) == {n["id"] for n in all_nodes}
    # root at x=0; x strictly increases along any parent→child edge
    assert pos1[SEC_PREFIX][0] == 0.0
    for parent, kids in children.items():
        for kid in kids:
            assert pos1[kid][0] > pos1[parent][0], (parent, kid)
    # unit coordinates
    for x, y in pos1.values():
        assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
