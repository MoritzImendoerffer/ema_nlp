"""Unit tests for harness.indexing.property_graph.to_graph (IR -> graph mapping).

The live build + retrieval are integration-verified against Neo4j (see work unit
20 / LIR-007/008 notes); here we lock the pure IR->nodes/relations mapping with
no infra: entity/chunk ids, HAS_CHUNK/PARENT_OF/LINKS_TO edges, links_to resolution.
"""

from __future__ import annotations

from harness.indexing.chunking import chunk_document, doc_id_for
from harness.indexing.ingest import IngestedDoc
from harness.indexing.links import ExtractedLink
from harness.indexing.profiles import ChunkingConfig
from harness.indexing.property_graph import to_graph

_LONG = "\n\n".join(
    f"## Section {i}\n\n" + ("regulatory guidance about acceptable intake limits " * 30)
    for i in range(20)
)
_URL_A = "https://www.ema.europa.eu/en/page-a"
_URL_B = "https://www.ema.europa.eu/en/doc-b_en.pdf"


def _doc(url: str, links=()) -> IngestedDoc:
    chunks = chunk_document(
        _LONG, source_url=url, title="T", config=ChunkingConfig(chunk_sizes=[512, 128])
    )
    return IngestedDoc(
        doc_id=doc_id_for(url), source_url=url, source_type="html", title="T",
        metadata={"committee": "CHMP", "topic_path": "/en/"}, chunk_nodes=chunks, links=list(links),
    )


def test_to_graph_structure():
    doc_a = _doc(_URL_A, links=[
        ExtractedLink(tgt_url=_URL_B, anchor="b", kind="file"),          # resolves (B in subset)
        ExtractedLink(tgt_url="https://fda.gov/x", anchor="x", kind="external"),  # does not
    ])
    doc_b = _doc(_URL_B)
    ents, chunks, rels = to_graph([doc_a, doc_b])

    assert {e.id for e in ents} == {doc_a.doc_id, doc_b.doc_id}
    assert all(e.label == "Document" for e in ents)

    expected_chunk_ids = {c.node_id for c in doc_a.chunk_nodes + doc_b.chunk_nodes}
    assert {c.id for c in chunks} == expected_chunk_ids

    has_chunk = [r for r in rels if r.label == "HAS_CHUNK"]
    parent_of = [r for r in rels if r.label == "PARENT_OF"]
    links_to = [r for r in rels if r.label == "LINKS_TO"]

    assert len(has_chunk) == len(chunks)
    assert all(r.target_id in expected_chunk_ids for r in has_chunk)
    assert len(parent_of) > 0  # multi-level hierarchy produced
    assert all(r.source_id in expected_chunk_ids and r.target_id in expected_chunk_ids for r in parent_of)

    # exactly one links_to edge, A -> B; the external link is dropped (not in subset)
    assert len(links_to) == 1
    assert links_to[0].source_id == doc_a.doc_id
    assert links_to[0].target_id == doc_b.doc_id


def test_links_to_dropped_when_target_absent():
    doc_a = _doc(_URL_A, links=[ExtractedLink(tgt_url=_URL_B, anchor="b", kind="file")])
    _ents, _chunks, rels = to_graph([doc_a])  # B not ingested
    assert [r for r in rels if r.label == "LINKS_TO"] == []
