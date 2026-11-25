"""scripts/backfill_parse_identity.py on the in-memory graph (work unit 27, TASK-012).

The 79,882 graph documents built before 2026-11-25 record no parse identity. The
backfill stamps them from the row the build used then: the first clean row the cursor
yields per URL (the old-rule row), not the row the new selection picks.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import mongomock
import pytest

from config import MONGO_DB
from harness.indexing.chunking import doc_id_for
from harness.indexing.ingest import PARSED_COLLECTION, text_sha256
from harness.indexing.profiles import (
    ChunkingConfig,
    IndexConfig,
    IndexProfile,
    RetrievalConfig,
    ScopeConfig,
)
from harness.indexing.property_graph import _embed_pass
from tests.graph_double import InMemoryCorpusGraph

_spec = importlib.util.spec_from_file_location(
    "backfill_parse_identity",
    Path(__file__).resolve().parents[1] / "scripts" / "backfill_parse_identity.py",
)
backfill_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = backfill_mod  # dataclasses look their module up there
_spec.loader.exec_module(backfill_mod)

_HTML = "https://www.ema.europa.eu/en/human-regulatory-overview/backfill-page"
_PDF = "https://www.ema.europa.eu/en/documents/scientific-guideline/backfill_en.pdf"
_CHUNKING = ChunkingConfig(chunk_sizes=[512, 128])
_TEXT = "# Title\n\n" + "A sentence about acceptable intake and CHMP assessment. " * 40


class _Embed:
    def get_text_embedding_batch(self, texts, show_progress=False):
        return [[0.1, 0.2, 0.3] for _ in texts]


def _row(url, parser, version, text, *, ct, at):
    return {"url": url, "parser": parser, "parser_version": version, "parsed_at": at,
            "content_type": ct, "text_format": "markdown", "error": "", "text": text}


@pytest.fixture
def world():
    """A graph built from two legacy rows, then unstamped as the pre-2026-11-25 graph is."""
    client = mongomock.MongoClient()
    col = client[MONGO_DB][PARSED_COLLECTION]
    col.insert_many([
        _row(_HTML, "trafilatura", "legacy", _TEXT, ct="text/html", at=dt.datetime(2026, 5, 27)),
        _row(_PDF, "pymupdf4llm", "legacy", _TEXT, ct="application/pdf", at=dt.datetime(2026, 5, 27)),
    ])
    graph = InMemoryCorpusGraph()
    profile = IndexProfile(name="t", index=IndexConfig(chunking=_CHUNKING, scope=ScopeConfig()),
                           retrieval=RetrievalConfig())
    _embed_pass(profile, graph, client, lambda _u: None, _Embed(), flush_chunks=1_000_000,
                metadata_lookup=lambda _u: None)
    for doc_id in (doc_id_for(_HTML), doc_id_for(_PDF)):
        for key in ("parser", "parser_version", "text_sha256"):
            graph.nodes[doc_id].properties.pop(key)
    # A newer HTML parse with other text: the new selection picks it, the backfill must not.
    col.insert_one(_row(_HTML, "trafilatura", "2.0.0", _TEXT + " New.", ct="text/html",
                        at=dt.datetime(2026, 11, 25)))
    return graph, client


def test_backfill_stamps_old_rule_row(world):
    graph, client = world
    report = backfill_mod.backfill(graph, client)
    assert report.stamped == 2 and report.unstamped_before == 2
    html = graph.nodes[doc_id_for(_HTML)].properties
    assert (html["parser"], html["parser_version"]) == ("trafilatura", "legacy")
    assert html["text_sha256"] == text_sha256(_TEXT)
    assert report.old_rule_differs == 1  # the HTML URL: its newer row is selected now


def test_backfill_is_resumable(world):
    graph, client = world
    backfill_mod.backfill(graph, client)
    assert backfill_mod.backfill(graph, client).stamped == 0


def test_backfill_dry_run_writes_nothing(world):
    graph, client = world
    report = backfill_mod.backfill(graph, client, dry_run=True)
    assert report.stamped == 2
    assert all(not s.stamped for s in graph.document_states().values())


def test_backfill_limit_stops_early(world):
    graph, client = world
    assert backfill_mod.backfill(graph, client, limit=1).stamped == 1


def test_verify_compares_chunk_ids(world):
    graph, client = world
    backfill_mod.backfill(graph, client)
    assert backfill_mod.verify(graph, client, _CHUNKING, 5)[:2] == (2, 2)
    # A chunk that the stamped row does not give makes the document unequal.
    some_chunk = graph.chunks_of(doc_id_for(_PDF))[0]
    some_chunk.text = "changed"
    equal, checked, unequal = backfill_mod.verify(graph, client, _CHUNKING, 5)
    assert (equal, checked) == (1, 2) and unequal == [doc_id_for(_PDF)]


def test_help_exits_zero():
    with pytest.raises(SystemExit) as exc:
        backfill_mod.main(["--help"])
    assert exc.value.code == 0
