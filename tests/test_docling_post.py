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
_BOX = {"l": 0.0, "t": 10.0, "r": 10.0, "b": 0.0, "coord_origin": "BOTTOMLEFT"}


def _cell(r, c, text, header=False):
    return {"row_span": 1, "col_span": 1, "start_row_offset_idx": r, "end_row_offset_idx": r + 1,
            "start_col_offset_idx": c, "end_col_offset_idx": c + 1, "text": text,
            "column_header": header, "row_header": False, "row_section": False, "fillable": False}


def _table(i, page, rows, captions=(), footnotes=()):
    cells = [_cell(r, c, t) for r, row in enumerate(rows) for c, t in enumerate(row)]
    return {"self_ref": f"#/tables/{i}", "parent": {"$ref": "#/body"}, "children": [], "content_layer": "body",
            "label": "table", "prov": [{"page_no": page, "bbox": dict(_BOX), "charspan": [0, 0]}],
            "captions": [{"$ref": r} for r in captions], "references": [],
            "footnotes": [{"$ref": r} for r in footnotes],
            "data": {"table_cells": cells, "num_rows": len(rows), "num_cols": len(rows[0]), "orientation": "rot_0", "grid": []},
            "annotations": []}


def _text(i, page, text, label="text", layer="body"):
    return {"self_ref": f"#/texts/{i}", "parent": {"$ref": "#/body"}, "children": [], "content_layer": layer,
            "label": label, "prov": [{"page_no": page, "bbox": dict(_BOX), "charspan": [0, len(text)]}], "orig": text, "text": text}


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
            "label": "picture", "prov": [{"page_no": 1, "bbox": dict(_BOX), "charspan": [0, 0]}], "captions": [], "references": [], "footnotes": []}
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


# ── rule 2: footnotes in tables (TASK-006) ─────────────────────────────────────


def test_footnote_mark_is_not_merged_into_number():
    """The model writes 12.5\\(^{1}\\); as plain text that would read 12.51."""
    import re

    doc = _doc(["#/tables/0"], [_table(0, 1, [["Dose", "Value"], ["Child", r"12.5\(^{1}\)"]])])
    out, counts = post_process(doc)
    cell = next(c for c in out["tables"][0]["data"]["table_cells"] if c["start_row_offset_idx"] == 1 and c["start_col_offset_idx"] == 1)
    assert cell["text"] == "12.5[^1]"
    assert re.findall(r"\d+(?:\.\d+)?", cell["text"])[0] == "12.5"
    assert counts["footnote_marks"] == 1


def test_footnote_mark_survives_compatibility_normalisation():
    """Lead session's review of 2026-11-26: a Unicode superscript, "12.5¹", becomes "12.51" under
    NFKC and NFKD, which full-text analysers and text cleaning apply. The mark must stay apart."""
    import re
    import unicodedata

    doc = _doc(["#/tables/0"], [_table(0, 1, [["Dose", "Ratio"], [r"12.5\(^{1}\)", "3.2ᵃ"]])])
    out, _ = post_process(doc)
    cells = {c["text"] for c in out["tables"][0]["data"]["table_cells"] if c["start_row_offset_idx"] == 1}
    assert cells == {"12.5[^1]", "3.2[^a]"}
    for form in ("NFKC", "NFKD"):
        for text, number, flat in (("12.5[^1]", "12.5", "12.51"), ("3.2[^a]", "3.2", "3.2a")):
            normal = unicodedata.normalize(form, text)
            assert re.findall(r"\d+(?:\.\d+)?", normal)[0] == number
            assert flat not in normal


def test_unit_exponents_are_not_footnote_marks():
    from corpus.parsers.docling_post import superscript_marks

    assert superscript_marks(r"1.73 m\(^{2}\)") == ("1.73 m^2", 0)
    assert superscript_marks(r"cells/mm\(^{3}\)") == ("cells/mm^3", 0)
    assert superscript_marks(r"mL min\(^{-1}\)") == ("mL min^-1", 0)
    assert superscript_marks(r"FAS\(^{2}\)") == ("FAS[^2]", 1)


def test_footnote_texts_attach_to_table():
    texts = [_text(0, 1, "a Full analysis set: all randomised patients."),
             _text(1, 1, "b Safety set."),
             _text(2, 1, "The study then continued.")]
    doc = _doc(["#/tables/0", "#/texts/0", "#/texts/1", "#/texts/2"],
               [_table(0, 1, [["Set", "n"], [r"FAS\(^{a}\)", "120"], [r"Safety Set\(^{b}\)", "118"]])], texts=texts)
    out, counts = post_process(doc)
    t = out["tables"][0]
    assert counts["footnotes_attached"] == 2
    assert [r["$ref"] for r in t["footnotes"]] == ["#/texts/0", "#/texts/1"]
    assert out["texts"][0]["parent"] == {"$ref": "#/tables/0"}
    assert out["body"]["children"] == [{"$ref": "#/tables/0"}, {"$ref": "#/texts/2"}]


def test_text_with_an_unused_mark_is_not_attached():
    doc = _doc(["#/tables/0", "#/texts/0"], [_table(0, 1, [["Set", "n"], [r"FAS\(^{a}\)", "120"]])],
               texts=[_text(0, 1, "c Something else.")])
    out, counts = post_process(doc)
    assert counts["footnotes_attached"] == 0 and out["body"]["children"][-1] == {"$ref": "#/texts/0"}


def test_exponent_is_left_for_rule_3_and_a_letter_mark_stays_apart():
    from corpus.parsers.docling_post import superscript_marks

    assert superscript_marks(r"2.06e^{-14}") == (r"2.06e^{-14}", 0)
    assert superscript_marks(r"x\(^{q}\)") == ("x[^q]", 1)


# ── rule 3: the model's markup (TASK-007) ──────────────────────────────────────


def test_latex_markup_becomes_text():
    from corpus.parsers.docling_post import convert_markup

    cases = {
        r"Cycle 1 Day 1 to 14 (\(\pm\) 2 days)": "Cycle 1 Day 1 to 14 (± 2 days)",
        r"Pharma\nceutical": "Pharma ceutical",
        r"2.06e^{-14}": "2.06e-14",
        r"37^{\circ}C": "37°C",
        r"x \(\geq\) 2 and y \(\le\) 5": "x ≥ 2 and y ≤ 5",
        r"\text{n} = 120": "n = 120",
        r"C_{max}": "Cmax",
        r"10^{9}/L": "10^9/L",
        r"3 \(\times\) daily": "3 × daily",
    }
    for raw, want in cases.items():
        assert convert_markup(raw)[0] == want, raw


def test_greek_letter_commands_become_greek_letters():
    """The owner, 2026-11-25: Greek symbols must be conserved."""
    from corpus.parsers.docling_post import _GREEK, convert_markup

    lower = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon phi chi psi omega"
    assert "".join(convert_markup("\\" + name)[0] for name in lower.split()) == "αβγδεζηθικλμνξοπρστυφχψω"
    upper = "Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega"
    assert "".join(convert_markup("\\" + name)[0] for name in upper.split()) == "ΓΔΘΛΞΠΣΥΦΨΩ"
    assert convert_markup(r"\(\alpha\)-tocopherol")[0] == "α-tocopherol"
    assert convert_markup(r"\mu g/kg")[0] == "μg/kg"
    assert convert_markup(r"\(\Delta\) AUC")[0] == "Δ AUC"
    assert len(_GREEK) >= 48


def test_unknown_command_is_left_as_written():
    from corpus.parsers.docling_post import convert_markup

    assert convert_markup(r"\foo bar") == (r"\foo bar", 0)


def test_markup_is_converted_in_tables_and_counted():
    doc = _doc(["#/tables/0"], [_table(0, 1, [["Window", "Agent"], [r"(\(\pm\) 2 days)", r"\(\alpha\)-tocopherol"]])])
    out, counts = post_process(doc)
    texts = {c["text"] for c in out["tables"][0]["data"]["table_cells"]}
    assert {"(± 2 days)", "α-tocopherol"} <= texts
    assert counts["markup_converted"] >= 2


def test_nu_and_neq_are_not_taken_for_a_line_break():
    from corpus.parsers.docling_post import convert_markup

    assert convert_markup(r"\nu = 3")[0] == "ν = 3"
    assert convert_markup(r"a \(\neq\) b")[0] == "a ≠ b"
    assert convert_markup(r"Pharma\nceutical")[0] == "Pharma ceutical"


# ── rule 4: the reference number from the page header (TASK-008) ───────────────


def test_reference_from_page_header():
    from corpus.metadata.text_metadata import text_metadata
    from corpus.parsers.docling_post import _body_text

    texts = [_text(0, 1, "EMA/CHMP/123456/2020 Rev. 1 Committee for Medicinal Products for Human Use", "page_header", "furniture"),
             _text(1, 1, "Guideline on the investigation of bioequivalence", "title"),
             _text(2, 1, "This guideline specifies the requirements."),
             _text(3, 2, "EMA/CHMP/123456/2020 Rev. 1", "page_header", "furniture")]
    doc = _doc(["#/texts/0", "#/texts/1", "#/texts/2", "#/texts/3"], [], texts=texts)
    assert text_metadata(_body_text(doc)).reference_number is None
    out, counts = post_process(doc)
    assert counts["header_reference_lifted"] == 1
    assert out["body"]["children"][0] == {"$ref": "#/texts/4"}
    assert out["texts"][4]["content_layer"] == "body" and out["texts"][4]["prov"][0]["page_no"] == 1
    assert text_metadata(_body_text(out)).reference_number == "EMA/CHMP/123456/2020"


def test_no_lift_when_the_body_holds_the_reference():
    texts = [_text(0, 1, "EMA/CHMP/123456/2020", "page_header", "furniture"),
             _text(1, 1, "Our reference EMA/CHMP/123456/2020 is in the body.")]
    doc = _doc(["#/texts/0", "#/texts/1"], [], texts=texts)
    out, counts = post_process(doc)
    assert counts["header_reference_lifted"] == 0 and len(out["texts"]) == 2


def test_greek_command_inside_a_word_and_capitals():
    """The table model writes \\Theta, \\Delta, \\Sigma inside Greek-language words (lead session's
    measurement on 30 pages, 2026-11-26)."""
    from corpus.parsers.docling_post import convert_markup

    assert convert_markup(r"ΣΥΝ\ThetaΕΣΗ")[0] == "ΣΥΝΘΕΣΗ"
    assert convert_markup(r"\beta-lactam")[0] == "β-lactam"
    assert convert_markup(r"\(\Sigma\) of doses")[0] == "Σ of doses"
