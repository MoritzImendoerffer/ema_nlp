"""The ranking of PDFs for Docling parsing (work unit 28, TASK-010)."""

import gzip
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "rank_pdfs_by_tables", Path(__file__).resolve().parents[1] / "scripts" / "rank_pdfs_by_tables.py")
rank_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rank_mod
_spec.loader.exec_module(rank_mod)

_PDF = Path(__file__).parent / "fixtures" / "docling" / "table_3x3.pdf"


def _table(cols: int, rows: int) -> str:
    head = "|" + "|".join(f"h{i}" for i in range(cols)) + "|"
    sep = "|" + "|".join("---" for _ in range(cols)) + "|"
    body = ["|" + "|".join(str(r * cols + c) for c in range(cols)) + "|" for r in range(rows - 1)]
    return "\n".join([head, sep, *body])


def test_score_counts_cells_of_wide_long_and_ragged_tables():
    small = _table(3, 4)  # 3 columns, 4 rows: not complex
    wide = _table(8, 2)  # 16 cells
    long = _table(2, 20)  # 40 cells
    ragged = "|a|b|\n|---|---|\n|1|2|3|"  # rows of 2 and 3 cells: 5
    text = "\n\n".join(["Intro.", small, wide, long, ragged])
    assert rank_mod.table_score(text) == {"score": 16 + 40 + 5, "tables": 4, "complex_tables": 3}


def test_pipes_without_a_separator_are_no_table():
    text = "|a|b|c|d|e|f|g|h|\n|1|2|3|4|5|6|7|8|"
    assert rank_mod.table_score(text) == {"score": 0, "tables": 0, "complex_tables": 0}


def test_order_is_score_then_pages_without_text_then_others():
    recs = [
        {"url": "u/other", "score": 0, "pages_without_text": 0},
        {"url": "u/scan", "score": 0, "pages_without_text": 3},
        {"url": "u/small", "score": 10, "pages_without_text": 5},
        {"url": "u/big", "score": 900, "pages_without_text": 0},
        {"url": "u/scan2", "score": 0, "pages_without_text": 9},
        {"url": "u/unknown", "score": 0, "pages_without_text": None},
    ]
    ranked = rank_mod.rank(recs)
    assert [r["url"] for r in ranked] == ["u/big", "u/small", "u/scan2", "u/scan", "u/other", "u/unknown"]
    assert [r["tier"] for r in ranked] == [1, 1, 2, 2, 3, 3]
    assert [r["rank"] for r in ranked] == [1, 2, 3, 4, 5, 6]


def test_cache_facts_reads_plain_and_gzip_bodies(tmp_path: Path):
    plain, packed = tmp_path / "plain", tmp_path / "packed"
    plain.mkdir()
    packed.mkdir()
    (plain / "response_body").write_bytes(_PDF.read_bytes())
    (packed / "response_body").write_bytes(gzip.compress(_PDF.read_bytes()))
    a, b = rank_mod.cache_facts(str(plain)), rank_mod.cache_facts(str(packed))
    assert (a["pages"], a["gzip"], a["cache_error"]) == (1, False, "")
    assert (b["pages"], b["gzip"], b["cache_error"]) == (1, True, "")
    assert a["pages_without_text"] == 0


def test_a_bad_cache_entry_is_recorded_not_raised(tmp_path: Path):
    assert rank_mod.cache_facts(None)["cache_error"] == "no cache_path"
    assert rank_mod.cache_facts(str(tmp_path / "missing"))["cache_error"].startswith("FileNotFoundError")


def test_build_ranking_end_to_end(tmp_path: Path):
    entry = tmp_path / "entry"
    entry.mkdir()
    (entry / "response_body").write_bytes(_PDF.read_bytes())
    rows = [{"url": "u/plain", "text": "No tables.", "meta": {"cache_path": str(entry)}},
            {"url": "u/table", "text": _table(9, 3), "meta": {"cache_path": str(entry)}}]
    ranked = rank_mod.build_ranking(rows, workers=1)
    assert [r["url"] for r in ranked] == ["u/table", "u/plain"]
    assert ranked[0]["score"] == 27 and ranked[0]["pages"] == 1 and ranked[0]["gzip"] is False
    assert set(ranked[0]) >= {"url", "score", "pages", "cache_path", "gzip", "pages_without_text", "rank", "tier"}
    assert rank_mod.summary(ranked)["score_above_0"] == 1
