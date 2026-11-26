"""The batch loop of the docling parser, with a stand-in parser (work unit 28, TASK-011).

The real parser runs only in the parse environment; ``make test-parse`` runs the command
there on two PDFs. These tests check the loop: skip, budget, failures, pause and stop.
"""

import json
from pathlib import Path

import pytest

from corpus.parsers import docling_batch, docling_pdf
from corpus.parsers.docling_batch import BatchSettings, run_batch
from corpus.parsers.docling_pdf import Conversion
from corpus.parsers.docling_store import FAILURES_FILE, RUN_FILE
from tests.test_docling_post import _doc, _table


@pytest.fixture(autouse=True)
def _no_torch(monkeypatch):
    monkeypatch.setattr(docling_pdf, "device", lambda: "cpu")
    monkeypatch.setattr(docling_pdf, "package_versions", lambda: {"docling": "stand-in"})


def _items(tmp_path: Path, n: int, pages: int = 10) -> list[dict]:
    out = []
    for i in range(n):
        entry = tmp_path / "cache" / f"e{i}"
        entry.mkdir(parents=True)
        (entry / "response_body").write_bytes(b"%PDF-1.4 stand-in " + str(i).encode())
        out.append({"url": f"https://www.ema.europa.eu/en/documents/x/doc-{i}_en.pdf", "cache_path": str(entry),
                    "pages": pages, "group": "ranked"})
    return out


class StandIn:
    """Returns a one-table document; fails for URLs in ``fail``; can create the stop file."""

    def __init__(self, fail=(), touch_after=None, stop_file=None):
        self.calls, self.fail, self.touch_after, self.stop_file = [], set(fail), touch_after, stop_file

    def __call__(self, pdf: bytes, name: str, range_pages: int) -> Conversion:
        self.calls.append(name)
        if self.touch_after and len(self.calls) == self.touch_after:
            self.stop_file.touch()
        if name in self.fail:
            return Conversion(status="PARTIAL_SUCCESS", error="status PARTIAL_SUCCESS: time limit", seconds=1.0)
        doc = _doc(["#/tables/0"], [_table(0, 1, [["Dose", "Value"], ["Child", r"12.5\(^{1}\)"]])])
        return Conversion(status="SUCCESS", document=doc, markdown="", pages=10, seconds=2.0,
                          counts={"pages": 10, "tables": 1, "cells": 4})


def _settings(tmp_path: Path, convert, **kw) -> BatchSettings:
    return BatchSettings(root=tmp_path / "parsed", budget_pages=kw.pop("budget_pages", 1000), workers=0,
                         convert=convert, sleep=kw.pop("sleep", lambda s: None), echo=lambda line: None,
                         log_path=tmp_path / "log.jsonl", **kw)


def test_parses_writes_and_skips_an_existing_folder(tmp_path: Path):
    items = _items(tmp_path, 2)
    first = run_batch(items, _settings(tmp_path, StandIn()))
    assert (first["parsed"], first["failed"], first["pages_parsed"]) == (2, 0, 20)
    runs = list((tmp_path / "parsed").rglob(RUN_FILE))
    assert len(runs) == 2 and json.loads(runs[0].read_text())["counts"]["footnote_marks"] == 1
    again = StandIn()
    second = run_batch(items, _settings(tmp_path, again))
    assert (second["skipped_existing"], second["parsed"], again.calls) == (2, 0, [])


def test_page_budget_stops_selection(tmp_path: Path):
    summary = run_batch(_items(tmp_path, 3), _settings(tmp_path, StandIn(), budget_pages=25))
    assert (summary["selected"], summary["budget_reached"], summary["parsed"]) == (2, 1, 2)


def test_failed_document_is_listed_and_the_batch_goes_on(tmp_path: Path):
    items = _items(tmp_path, 3)
    summary = run_batch(items, _settings(tmp_path, StandIn(fail={"doc-1_en.pdf"})))
    assert (summary["parsed"], summary["failed"]) == (2, 1)
    failures = [json.loads(x) for x in (tmp_path / "parsed" / FAILURES_FILE).read_text().splitlines()]
    assert [f["url"] for f in failures] == [items[1]["url"]] and "PARTIAL_SUCCESS" in failures[0]["error"]
    assert len(list((tmp_path / "parsed").rglob(RUN_FILE))) == 2
    log = [json.loads(x) for x in (tmp_path / "log.jsonl").read_text().splitlines()]
    assert [x["status"] for x in log] == ["parsed", "failed", "parsed"]


def test_unreadable_cache_entry_is_listed(tmp_path: Path):
    items = _items(tmp_path, 1) + [{"url": "https://x/doc-gone_en.pdf", "cache_path": str(tmp_path / "gone"), "pages": 5}]
    summary = run_batch(items, _settings(tmp_path, StandIn()))
    assert (summary["parsed"], summary["failed"], summary["unreadable"]) == (1, 1, 1)
    assert "read: FileNotFoundError" in (tmp_path / "parsed" / FAILURES_FILE).read_text()


def test_stop_file_is_honoured_between_documents(tmp_path: Path):
    stop = tmp_path / "parsed" / docling_batch.STOP_FILE
    stop.parent.mkdir(parents=True)
    stand_in = StandIn(touch_after=2, stop_file=stop)
    summary = run_batch(_items(tmp_path, 4), _settings(tmp_path, stand_in))
    assert (summary["parsed"], summary["stopped"], len(stand_in.calls)) == (2, True, 2)


def test_pauses_on_schedule(tmp_path: Path):
    slept = []
    summary = run_batch(_items(tmp_path, 5), _settings(tmp_path, StandIn(), pause_every=2, pause_seconds=7,
                                                       sleep=slept.append))
    assert summary["parsed"] == 5 and slept == [7, 7] and summary["pauses"] == 2


def test_page_ranges():
    assert docling_pdf.page_ranges(60, 100) == [None]
    assert docling_pdf.page_ranges(250, 100) == [(1, 100), (101, 200), (201, 250)]
    assert docling_pdf.page_ranges(250, 0) == [None]
