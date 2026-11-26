"""The batch report of the docling parser (work unit 28, TASK-012).

Two stored parses (``tests/fixtures/docling/batch/``, made by the batch command in the parse
environment on 2026-11-26): the synthetic 3x3 table and the 8-page fixture PDF.
"""

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "report_docling_batch", Path(__file__).resolve().parents[1] / "scripts" / "report_docling_batch.py")
rep = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rep
_spec.loader.exec_module(rep)

_FIX = Path(__file__).parent / "fixtures"
_HASH = "6eceaf4e"
_T = "https://www.ema.europa.eu/en/documents/test/table_3x3_en.pdf"
_F = "https://www.ema.europa.eu/en/documents/test/fixture_pdf_0_en.pdf"


@pytest.fixture
def batch(tmp_path: Path):
    root = tmp_path / "parsed"
    shutil.copytree(_FIX / "docling" / "batch", root)
    items = []
    for url, pdf, group in ((_T, _FIX / "docling" / "table_3x3.pdf", "ranked"), (_F, _FIX / "fixture_pdf_0.pdf", "random")):
        entry = tmp_path / "cache" / pdf.stem
        entry.mkdir(parents=True)
        (entry / "response_body").write_bytes(pdf.read_bytes())
        items.append({"url": url, "cache_path": str(entry), "group": group})
    return root, items


def test_report_on_two_parsed_documents(batch):
    root, items = batch
    recs = rep.collect(items, root, _HASH, legacy={_T: "Table 1. Dose by age group\n2 to 5 years 12.5 once daily"})
    s = rep.summarise(recs)
    assert (s["parsed"], s["failed"], s["not_parsed"]) == (2, [], 0)
    assert s["rates"]["ranked"]["n"] == 1 and s["rates"]["random"]["pages"] == 8
    assert s["post_processing"]["tables_joined"] == 1 and s["post_processing"]["markup_converted"] == 6
    t = s["table_numbers"]
    assert t["tables_checked"] == 5 and t["layer_numbers"] == t["layer_held_by_cells"] == 42
    assert t["cell_share"] == 1.0 and t["flattened_mark_pairs"] == 0
    assert s["bytes_per_page"]["doc.raw.json"]["gzip"] < s["bytes_per_page"]["doc.raw.json"]["plain"]
    assert s["cjk"]["total"] == 0
    assert s["legacy"]["n"] == 1 and s["legacy"]["words_share"] == 1.0 and s["legacy"]["numbers_share"] == 1.0
    md = rep.render(s, "test")
    for heading in ("## Rates", "## Failures", "## Bytes per page", "## Post-processing", "## Table numbers",
                    "## Greek letters", "## CJK characters", "## Against the legacy text"):
        assert heading in md
    assert "Line rule:" in md and "cannot see a number in the wrong cell" in md


def test_failure_without_a_folder_is_listed(batch, tmp_path: Path):
    root, items = batch
    gone = tmp_path / "cache" / "gone"
    gone.mkdir()
    (gone / "response_body").write_bytes(b"%PDF-1.4 never parsed")
    url = "https://www.ema.europa.eu/en/documents/test/gone_en.pdf"
    (root / "failures.jsonl").write_text(json.dumps({"url": url, "error": "status PARTIAL_SUCCESS: time limit"}) + "\n")
    s = rep.summarise(rep.collect(items + [{"url": url, "cache_path": str(gone), "group": "random"}], root, _HASH))
    assert s["failed"] == [{"url": url, "group": "random", "error": "status PARTIAL_SUCCESS: time limit"}]
    assert s["parsed"] == 2


def test_rate_fit_needs_three_documents():
    recs = [{"status": "parsed", "seconds": 0.5 * p + 2 * t + 0.1 * c, "pages": p + 1, "pages_without_tables": p,
             "tables": t, "cells": c} for p, t, c in ((10, 1, 20), (4, 3, 90), (30, 0, 0), (7, 2, 40))]
    fit = rep.rates(recs)["fit"]
    assert (fit["per_page_without_tables"], fit["per_table"], fit["per_cell"]) == (0.5, 2.0, 0.1)
    assert rep.rates(recs[:2])["fit"] is None


def test_flattened_footnote_mark_is_its_own_column():
    """Lead session's review, 2026-11-26: the layer says 12.51 where the cell says 12.5[^1]."""
    res = rep.number_compare("Dose 12.51 mg and 25 mg", ["12.5[^1]", "25"])
    assert res == {"layer_numbers": 1, "layer_held_by_cells": 1, "cell_numbers": 1, "cells_held_by_layer": 1,
                   "flattened_mark_pairs": 1}
    plain_miss = rep.number_compare("Dose 12.6", ["12.5"])
    assert (plain_miss["layer_held_by_cells"], plain_miss["flattened_mark_pairs"]) == (0, 0)


def test_greek_line_rule():
    split = rep.greek_split(["50 µg of β-blocker", "ΣΥΝΘΕΣΗ και"])
    assert split["symbols"] == {"μ": 1, "β": 1} and split["mu"] == {"μ": 1}  # µ (U+00B5) is μ after NFKC
    assert sum(split["language"].values()) == 10
    cmp = rep.greek_compare(["50 μg of β-blocker"], ["50 μg of -blocker α"])
    assert (cmp["symbols_held"], cmp["symbols_of"], cmp["mu_held"], cmp["returned_not_in_layer"]) == (1, 2, 1, 1)
