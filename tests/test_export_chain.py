"""Unit tests for the chain_html exporter (retrieval-chain debug view)."""

import json

from harness.attribution import build_attribution
from harness.export import ExportOptions, get_exporter
from harness.export.bundle import ExportBundle
from harness.export.chain_html import _evolution_rows
from harness.schemas import Citation, Claim, RegulatoryAnswer
from harness.tools.events import ChainStep, NodeRef

FULL = "Background. The Acceptable Intake for NDMA is 96 ng/day. Trailing."


def _node(doc: str, chunk: str, origin: str = "vector", **kw) -> NodeRef:
    return NodeRef(
        doc_id=doc,
        chunk_id=chunk,
        matched_chunk=chunk,
        source_url=f"https://ema.eu/{doc}",
        title=f"Title {doc}",
        category=kw.pop("category", "qa"),
        doc_type=kw.pop("doc_type", "questions-and-answers"),
        score=kw.pop("score", 0.9),
        retrieval_origin=origin,
        **kw,
    )


def _bundle(chain: list[dict] | None = None) -> ExportBundle:
    answer = RegulatoryAnswer(
        answer="The Acceptable Intake for NDMA is 96 ng/day.",
        claims=[
            Claim(
                text="The Acceptable Intake for NDMA is 96 ng/day.",
                citations=[Citation(source_url="https://ema.eu/d1", chunk_id="c1")],
            )
        ],
        citations=[
            Citation(
                source_url="https://ema.eu/d1", doc_id="d1", chunk_id="c1",
                title="Title d1", category="qa",
                quote="Acceptable Intake for NDMA is 96 ng/day", score=0.91,
            )
        ],
    )
    steps = chain if chain is not None else [
        ChainStep(
            seq=1,
            tool="ema_search",
            args={"query": "NDMA acceptable intake </script>", "source_category": ""},
            notes=["[routing: rule 'nitrosamine' -> filter qa]"],
            nodes=[_node("d1", "c1"), _node("d2", "c2", category="epar")],
            duration_ms=42.0,
            output_chars=100,
            raw_output="[1] source=https://ema.eu/d1 ...",
        ).to_dict(),
        ChainStep(
            seq=2,
            tool="ema_search",
            args={"query": "nitrosamine limits", "source_category": "scientific_guideline"},
            notes=["[category filter: scientific_guideline]"],
            nodes=[
                _node("d1", "c9"),  # same doc again -> not "new"
                _node("d3", "c3", origin="link_expansion", linked_from=["d1"]),
            ],
            duration_ms=17.0,
        ).to_dict(),
        ChainStep(
            seq=3,
            tool="topic_context",
            args={"topic": "referral_procedures", "query": "nitrosamine", "page": 1},
            notes=["[topic: referral_procedures]"],
            nodes=[_node("d4", "c4", origin="topic_subgraph", topic_hub="referral_procedures")],
        ).to_dict(),
    ]
    return ExportBundle(
        question="What is the AI for NDMA?",
        answer=answer,
        attribution=build_attribution(answer, [FULL]),
        recipe_name="steered_agent",
        run_id="run-987654321",
        trace_id="tr-abcdef",
        trace_url="http://localhost:5000/#/traces?x=1",
        msg_num=2,
        asked_at="2026-07-19T10:00:00",
        chain=steps,
    )


def _render(bundle: ExportBundle, options: ExportOptions | None = None) -> str:
    return get_exporter("chain_html").render(bundle, options or ExportOptions())


def test_timeline_renders_steps_in_order_with_notes_and_badges():
    html = _render(_bundle())
    assert html.startswith("<!doctype html>")
    i1 = html.index("Step 1")
    i2 = html.index("Step 2")
    i3 = html.index("Step 3")
    assert i1 < i2 < i3
    assert "[routing: rule &#x27;nitrosamine&#x27; -&gt; filter qa]" in html
    assert "[category filter: scientific_guideline]" in html
    assert "badge vector" in html
    assert "badge link_expansion" in html
    assert "badge topic_subgraph" in html
    assert "← from d1" in html  # link-expansion provenance
    assert "hub referral_procedures" in html
    assert "42 ms" in html


def test_new_and_cited_flags():
    html = _render(_bundle())
    # d1 is cited (chunk c1 matches the reference) and first appears in step 1
    assert "cited [1]" in html
    # d1 reappears in step 2 with a different chunk -> only one "new" badge for d1:
    # count 'new' badges: d1, d2, d3, d4 => 4 distinct docs => 4 new badges
    assert html.count("badge new") == 4


def test_evolution_rows_aggregate_per_document():
    bundle = _bundle()
    rows = _evolution_rows(bundle.chain, bundle.attribution)
    by_doc = {r["doc_key"]: r for r in rows}
    assert list(by_doc) == ["d1", "d2", "d3", "d4"]  # first-seen order
    assert by_doc["d1"]["first_step"] == 1
    assert by_doc["d1"]["chunk_count"] == 2  # c1 + c9
    assert by_doc["d1"]["cited_n"] == 1
    assert by_doc["d3"]["origins"] == ["link_expansion"]
    assert by_doc["d2"]["cited_n"] is None


def test_raw_output_gated_by_option():
    bundle = _bundle()
    assert "Raw tool output" not in _render(bundle)  # default off
    html = _render(bundle, ExportOptions(include_chain_output=True))
    assert "Raw tool output" in html
    assert "source=https://ema.eu/d1" in html


def test_escaping_and_selfcontainment():
    html = _render(_bundle())
    assert "</script> ..." not in html  # query content escaped
    assert "&lt;/script&gt;" in html
    stripped = html
    for allowed in ("https://ema.eu/", "http://localhost:5000"):
        stripped = stripped.replace(allowed, "")
    assert "http://" not in stripped and "https://" not in stripped  # no external assets
    start = html.index("id='ema-export-bundle'>") + len("id='ema-export-bundle'>")
    end = html.index("</script>", start)
    embedded = json.loads(html[start:end])
    assert len(embedded["chain"]) == 3
    assert embedded["chain"][0]["tool"] == "ema_search"


def test_chainless_bundle_renders_sane_document():
    html = _render(_bundle(chain=[]))
    assert "No chain captured" in html
    assert "Context evolution" not in html
    assert html.startswith("<!doctype html>")


def test_filename_has_chain_suffix():
    exporter = get_exporter("chain_html")
    assert exporter.filename(_bundle(), ExportOptions()) == "ema_answer_2_run-9876_chain.html"


def test_subgraph_svg_nodes_edges_and_gating():
    from harness.export.chain_html import _subgraph_svg

    bundle = _bundle()
    html = _render(bundle)  # include_chain_graph defaults True
    assert "<svg" in html and "Documents touched this turn" in html
    svg = _subgraph_svg(bundle.chain, bundle.attribution)
    assert svg.count("<circle") == 4  # one per distinct doc
    assert "stroke-dasharray" in svg  # the d1 -> d3 link-expansion edge
    assert 'data-doc=\'d1\'' in svg and 'data-doc=\'d3\'' in svg
    assert "cited [1]" in svg  # d1's tooltip carries the citation
    # gated off
    assert "<svg" not in _render(bundle, ExportOptions(include_chain_graph=False))
    # fewer than 2 docs -> no svg at all
    single = _bundle(chain=[bundle.chain[2]])
    assert _subgraph_svg(single.chain, single.attribution) == ""


def test_subgraph_layout_circle_fallback_without_igraph(monkeypatch):
    import builtins

    from harness.export import chain_html as ch

    real_import = builtins.__import__

    def _no_igraph(name, *args, **kwargs):
        if name == "igraph":
            raise ImportError("igraph unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_igraph)
    pos = ch._subgraph_layout(["a", "b", "c"], [("a", "b")])
    assert set(pos) == {"a", "b", "c"}
    assert all(0.0 <= v <= 1.0 for xy in pos.values() for v in xy)
