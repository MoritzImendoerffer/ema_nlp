"""Post-processing of a stored Docling document (work unit 28, TASK-005 to TASK-008).

The rules run on the JSON of doc.raw.json in plain Python, so .venv and the gate test them.
The real fixture is the Docling 2.153.0 export of an EMA procedural-steps PDF whose one table
runs over four pages and came out as four tables.
"""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path

from corpus.parsers.docling_post import _rows, post_process

_FIX = Path(__file__).parent / "fixtures" / "docling"


def _cell(r, c, text, header=False):
    return {"row_span": 1, "col_span": 1, "start_row_offset_idx": r, "end_row_offset_idx": r + 1,
            "start_col_offset_idx": c, "end_col_offset_idx": c + 1, "text": text,
            "column_header": header, "row_header": False, "row_section": False, "fillable": False}


def _table(i, page, rows, captions=(), footnotes=()):
    cells = [_cell(r, c, t) for r, row in enumerate(rows) for c, t in enumerate(row)]
    return {"self_ref": f"#/tables/{i}", "parent": {"$ref": "#/body"}, "children": [], "content_layer": "body",
            "label": "table", "prov": [{"page_no": page, "bbox": {}, "charspan": [0, 0]}],
            "captions": [{"$ref": r} for r in captions], "references": [],
            "footnotes": [{"$ref": r} for r in footnotes],
            "data": {"table_cells": cells, "num_rows": len(rows), "num_cols": len(rows[0]), "orientation": None, "grid": []},
            "annotations": []}


def _text(i, page, text, label="text", layer="body"):
    return {"self_ref": f"#/texts/{i}", "parent": {"$ref": "#/body"}, "children": [], "content_layer": layer,
            "label": label, "prov": [{"page_no": page, "bbox": {}, "charspan": [0, len(text)]}], "orig": text, "text": text}


def _doc(order, tables, texts=(), pictures=()):
    return {"schema_name": "DoclingDocument", "version": "1.9.0", "name": "t", "origin": None,
            "furniture": {"self_ref": "#/furniture", "children": [], "content_layer": "furniture", "name": "_root_", "label": "unspecified"},
            "body": {"self_ref": "#/body", "children": [{"$ref": r} for r in order], "content_layer": "body", "name": "_root_", "label": "unspecified"},
            "groups": [], "texts": list(texts), "pictures": list(pictures), "tables": list(tables),
            "key_value_items": [], "form_items": [], "pages": {}}


HEAD = ["Procedure", "Scope", "Date"]


def test_split_table_is_joined():
    doc = _doc(["#/tables/0", "#/texts/0", "#/tables/1"],
               [_table(0, 1, [HEAD, ["A", "x", "2020"]]), _table(1, 2, [["B", "y", "2021"], ["C", "z", "2022"]])],
               texts=[_text(0, 1, "Page 1/2", "page_footer", "furniture")])
    out, counts = post_process(doc)
    assert counts["tables_joined"] == 1 and len(out["tables"]) == 1
    t = out["tables"][0]
    assert [p["page_no"] for p in t["prov"]] == [1, 2]
    assert t["data"]["num_rows"] == 4 and [r[0] for r in _rows(t)] == ["procedure", "a", "b", "c"]
    assert out["body"]["children"] == [{"$ref": "#/tables/0"}, {"$ref": "#/texts/0"}]
    assert len(t["data"]["grid"]) == 4


def test_repeated_header_is_dropped():
    doc = _doc(["#/tables/0", "#/tables/1"],
               [_table(0, 1, [HEAD, ["A", "x", "2020"]]), _table(1, 2, [HEAD, ["B", "y", "2021"]])])
    out, _ = post_process(doc)
    assert [r[0] for r in _rows(out["tables"][0])] == ["procedure", "a", "b"]


def test_different_columns_are_not_joined():
    doc = _doc(["#/tables/0", "#/tables/1"],
               [_table(0, 1, [HEAD, ["A", "x", "2020"]]), _table(1, 2, [["B", "y"]])])
    out, counts = post_process(doc)
    assert counts["tables_joined"] == 0 and len(out["tables"]) == 2


def test_text_between_parts_ends_the_table_but_a_logo_does_not():
    blocked = _doc(["#/tables/0", "#/texts/0", "#/tables/1"],
                   [_table(0, 1, [HEAD]), _table(1, 2, [["B", "y", "2021"]])], texts=[_text(0, 1, "A new paragraph.")])
    assert post_process(blocked)[1]["tables_joined"] == 0
    logo = {"self_ref": "#/pictures/0", "parent": {"$ref": "#/body"}, "children": [], "content_layer": "body",
            "label": "picture", "prov": [{"page_no": 1, "bbox": {}, "charspan": [0, 0]}], "captions": [], "references": [], "footnotes": []}
    passes = _doc(["#/tables/0", "#/pictures/0", "#/tables/1"],
                  [_table(0, 1, [HEAD]), _table(1, 2, [["B", "y", "2021"]])], pictures=[logo])
    assert post_process(passes)[1]["tables_joined"] == 1


def test_input_is_not_changed():
    doc = _doc(["#/tables/0", "#/tables/1"], [_table(0, 1, [HEAD]), _table(1, 2, [["B", "y", "2021"]])])
    before = copy.deepcopy(doc)
    post_process(doc)
    assert doc == before


def test_join_is_linear():
    """200 parts, one per page: one pass, no rebuild of the element list per join."""
    tables = [_table(0, 1, [HEAD])] + [_table(i, i + 1, [[f"r{i}", "s", "d"]]) for i in range(1, 200)]
    doc = _doc([f"#/tables/{i}" for i in range(200)], tables)
    t0 = time.time()
    out, counts = post_process(doc)
    assert time.time() - t0 < 5
    assert counts["tables_joined"] == 199 and len(out["tables"]) == 1
    assert len(out["tables"][0]["prov"]) == 200 and out["tables"][0]["data"]["num_rows"] == 200


def test_real_procedural_steps_table_over_four_pages():
    raw = json.loads((_FIX / "trepulmix_procedural_steps.raw.json").read_text())
    out, counts = post_process(raw)
    assert len(raw["tables"]) == 4
    assert counts["tables_joined"] == 3 and len(out["tables"]) == 1
    t = out["tables"][0]
    assert [p["page_no"] for p in t["prov"]] == [1, 2, 3, 4]
    assert t["data"]["num_rows"] == 16 and t["data"]["num_cols"] == 6
    assert len(t["footnotes"]) == 3
    assert "#/tables/1" not in json.dumps(out)
