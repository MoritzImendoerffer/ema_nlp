"""Unit tests for scripts/build_graph_map.py (layout, payload, emitted HTML).

Offline: fake document rows, no Neo4j. The layout tests need the ``viz`` extra
(python-igraph) and are skipped without it.
"""

import base64
import gzip
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "build_graph_map", _REPO / "scripts" / "build_graph_map.py"
)
bgm = importlib.util.module_from_spec(spec)
sys.modules["build_graph_map"] = bgm
spec.loader.exec_module(bgm)

igraph_missing = importlib.util.find_spec("igraph") is None


def _docs(n, category="qa", prefix="d"):
    return [
        {
            "id": f"{prefix}{i}",
            "title": f"Title {prefix}{i}",
            "source_url": f"{bgm.URL_PREFIX}/page/{prefix}{i}",
            "category": category,
            "doc_type": "guideline",
            "audience": "Human",
            "site_topic": "",
            "topic_path": "Human > Topic",
        }
        for i in range(n)
    ]


@pytest.mark.skipif(igraph_missing, reason="needs the viz extra (python-igraph)")
def test_layout_positions_every_node_and_separates_components():
    # Two components (a 5-chain and a 4-cycle) + 2 isolates + 1 pair.
    nodes = _docs(13)
    edges = (
        [(f"d{i}", f"d{i+1}") for i in range(4)]                # comp A: d0..d4
        + [("d5", "d6"), ("d6", "d7"), ("d7", "d8"), ("d8", "d5")]  # comp B: d5..d8
        + [("d11", "d12")]                                       # pair -> band
    )
    pos = bgm.compute_layout(nodes, edges, seed=7)
    assert set(pos) == {n["id"] for n in nodes}  # every node placed
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    assert all(isinstance(v, float) for v in xs + ys)

    def bbox(ids):
        pts = [pos[i] for i in ids]
        return (
            min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[0] for p in pts), max(p[1] for p in pts),
        )

    a = bbox([f"d{i}" for i in range(5)])
    b = bbox([f"d{i}" for i in range(5, 9)])
    # Component boxes must not overlap (shelf packing separates them).
    disjoint_x = a[2] < b[0] or b[2] < a[0]
    disjoint_y = a[3] < b[1] or b[3] < a[1]
    assert disjoint_x or disjoint_y
    # Isolates/pairs sit in the band strictly below both component boxes.
    band_min_y = min(pos[i][1] for i in ("d9", "d10", "d11", "d12"))
    assert band_min_y > max(a[3], b[3])


@pytest.mark.skipif(igraph_missing, reason="needs the viz extra (python-igraph)")
def test_layout_is_deterministic_for_a_seed():
    nodes = _docs(30)
    edges = [(f"d{i}", f"d{(i * 7 + 1) % 30}") for i in range(30)]
    assert bgm.compute_layout(nodes, edges, seed=42) == bgm.compute_layout(
        nodes, edges, seed=42
    )


def test_payload_is_columnar_with_string_tables():
    nodes = _docs(3) + _docs(2, category="epar", prefix="e")
    edges = [("d0", "d1"), ("d1", "d2"), ("e0", "d0"), ("x-missing", "d0")]
    positions = {n["id"]: (float(i), float(i * 2)) for i, n in enumerate(nodes)}
    payload = bgm.build_payload(nodes, edges, positions)
    assert payload["meta"]["node_count"] == 5
    assert payload["meta"]["edge_count"] == 3  # dangling edge dropped
    assert payload["categories"] == ["epar", "qa"]
    cat_of = dict(zip(payload["nodes"]["id"], payload["nodes"]["cat"]))
    assert payload["categories"][cat_of["d0"]] == "qa"
    assert payload["categories"][cat_of["e0"]] == "epar"
    # url prefix factored out; in-degree counted on targets
    assert payload["nodes"]["url"][0] == "/page/d0"
    in_deg = dict(zip(payload["nodes"]["id"], payload["nodes"]["in_deg"]))
    assert in_deg["d0"] == 1 and in_deg["d1"] == 1 and in_deg["e0"] == 0
    assert len(payload["edges"]) == 6  # flat int pairs


def test_emit_html_is_selfcontained_and_payload_decodable(tmp_path):
    nodes = _docs(4)
    positions = {n["id"]: (1.0, 2.0) for n in nodes}
    payload = bgm.build_payload(nodes, [("d0", "d1")], positions)
    out = tmp_path / "map.html"
    bgm.emit_html(payload, out)
    html = out.read_text(encoding="utf-8")
    # no external scripts/styles — everything inline
    assert "src=\"http" not in html and "src='http" not in html
    assert "href=\"http" not in html and "href='http" not in html
    assert "graphology" in html and "Sigma" in html  # vendor JS inlined
    # embedded payload round-trips through gzip+base64
    marker = 'data-encoding="gzip-base64">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    decoded = json.loads(gzip.decompress(base64.b64decode(html[start:end].strip())))
    assert decoded == payload


def test_emit_html_raw_json_mode(tmp_path):
    nodes = _docs(2)
    payload = bgm.build_payload(nodes, [], {n["id"]: (0.0, 0.0) for n in nodes})
    out = tmp_path / "map.html"
    bgm.emit_html(payload, out, raw_json=True)
    html = out.read_text(encoding="utf-8")
    marker = 'data-encoding="json">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    assert json.loads(html[start:end]) == payload
