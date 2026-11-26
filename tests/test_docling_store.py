"""The stored shape of a Docling parse (work unit 28, TASK-001)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from corpus.parsers.docling_store import (
    doc_id_for,
    options_hash,
    parse_folder,
    parser_version,
    slug_for,
)

_URL = "https://www.ema.europa.eu/en/documents/procedural-steps-after/repatha-epar-procedural-steps-taken-scientific-information-after-authorisation_en.pdf"


def test_doc_id_is_slug_and_12_hex():
    pdf = b"%PDF-1.5 example bytes"
    doc_id = doc_id_for(_URL, pdf)
    slug, digest = doc_id.rsplit("_", 1)
    assert digest == hashlib.sha256(pdf).hexdigest()[:12]
    assert len(slug) <= 40 and slug.startswith("repatha-epar-procedural-steps")
    assert not slug.endswith("-")


def test_slug_fallback_and_pdf_n_suffix():
    assert slug_for("https://www.ema.europa.eu/") == "www-ema-europa-eu"
    assert slug_for("https://x.test/") == "x-test"
    assert slug_for("https://x.test/%%%.pdf") == "doc"
    assert slug_for("https://x.test/a/report_en.pdf-1") == "report-en"


def test_same_bytes_share_an_id_other_bytes_do_not():
    assert doc_id_for(_URL, b"a") == doc_id_for(_URL, b"a")
    assert doc_id_for(_URL, b"a") != doc_id_for(_URL, b"b")


def test_options_hash_is_stable():
    a = {"ocr": {"lang": "en", "version": "PP-OCRv5"}, "table": "paddleocr-vl", "heron": "8f39ad3"}
    b = {"heron": "8f39ad3", "table": "paddleocr-vl", "ocr": {"version": "PP-OCRv5", "lang": "en"}}
    assert options_hash(a) == options_hash(b)
    assert len(options_hash(a)) == 8
    assert options_hash(a) != options_hash({**a, "table": "tableformer"})


def test_folder_path(tmp_path: Path):
    folder = parse_folder(tmp_path, "repatha_0123456789ab", "deadbeef")
    assert folder == tmp_path / "repatha_0123456789ab" / "docling@deadbeef"
    assert parser_version("2.153.0", "deadbeef") == "2.153.0+deadbeef"


def test_config_roots():
    import config

    assert config.PARSED_ROOT.name == "parsed"
    assert str(config.DOCLING_ENV).endswith("envs/docling") or "EMA_DOCLING_ENV" in __import__("os").environ


# ── the writer (TASK-009) ──────────────────────────────────────────────────────

import json  # noqa: E402

from corpus.parsers.docling_store import (  # noqa: E402
    FAILURES_FILE,
    MONGO_TEXT_MAX_BYTES,
    append_failure,
    mongo_row,
    run_record,
    write_parse,
)


def _run():
    return run_record(url=_URL, doc_id="d_0123456789ab", source_sha="ab" * 32, options={"x": 1}, opts_hash="deadbeef",
                      versions={"docling": "2.153.0"}, counts={"pages": 3}, seconds=1.234, device="cuda")


def test_write_creates_three_files(tmp_path: Path):
    folder = parse_folder(tmp_path, "d_0123456789ab", "deadbeef")
    write_parse(folder, {"raw": 1}, {"doc": 1}, _run())
    assert sorted(p.name for p in folder.iterdir()) == ["doc.json", "doc.raw.json", "run.json"]
    run = json.loads((folder / "run.json").read_text())
    assert run["options_hash"] == "deadbeef" and run["seconds"] == 1.23 and run["parser"] == "docling"
    assert not list(tmp_path.rglob("*.tmp")) and not list(tmp_path.rglob("*.old"))


def test_failed_write_keeps_previous_folder(tmp_path: Path):
    folder = parse_folder(tmp_path, "d_0123456789ab", "deadbeef")
    write_parse(folder, {"raw": "first"}, {"doc": "first"}, _run())
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    with pytest.raises(TypeError):
        write_parse(folder, {"raw": "second"}, {"doc": object()}, _run())  # not serialisable
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
    assert not list(tmp_path.rglob("*.tmp"))


def test_rewrite_replaces_the_folder(tmp_path: Path):
    folder = parse_folder(tmp_path, "d_0123456789ab", "deadbeef")
    write_parse(folder, {"raw": "first"}, {"doc": "first"}, _run())
    write_parse(folder, {"raw": "second"}, {"doc": "second"}, _run())
    assert json.loads((folder / "doc.raw.json").read_text()) == {"raw": "second"}


def test_failure_is_listed(tmp_path: Path):
    append_failure(tmp_path, url=_URL, doc_id="d_0123456789ab", sha256="ab" * 32, error="status PARTIAL_SUCCESS: timeout")
    append_failure(tmp_path, url=_URL + "2", doc_id="e_0123456789ab", sha256="cd" * 32, error="exception")
    lines = [json.loads(x) for x in (tmp_path / FAILURES_FILE).read_text().splitlines()]
    assert [x["doc_id"] for x in lines] == ["d_0123456789ab", "e_0123456789ab"]
    assert lines[0]["error"].startswith("status PARTIAL_SUCCESS")
    assert not [p for p in tmp_path.iterdir() if p.is_dir()]


def test_mongo_row_shape():
    import mongomock

    from config import MONGO_DB
    from corpus.sources.parsed_documents import write_parsed_document

    row = mongo_row(url=_URL, doc_id="d_0123456789ab", folder_rel="d_0123456789ab/docling@deadbeef",
                    source_sha="ab" * 32, markdown="# Title\n\nText.", counts={"pages": 3},
                    docling_version="2.153.0", opts_hash="deadbeef")
    client = mongomock.MongoClient()
    write_parsed_document(row, client=client)
    stored = client[MONGO_DB]["parsed_documents"].find_one({"url": _URL})
    assert (stored["parser"], stored["parser_version"]) == ("docling", "2.153.0+deadbeef")
    assert stored["content_type"] == "application/pdf"
    assert stored["meta"]["folder"] == "d_0123456789ab/docling@deadbeef" and stored["meta"]["text_truncated"] is False


def test_mongo_row_text_is_cut_below_the_limit():
    big = "é" * (MONGO_TEXT_MAX_BYTES // 2 + 10)  # 2 bytes each: just over the limit
    row = mongo_row(url=_URL, doc_id="d", folder_rel="d/x", source_sha="0", markdown=big, counts={},
                    docling_version="2.153.0", opts_hash="deadbeef")
    assert len(row.text.encode("utf-8")) <= MONGO_TEXT_MAX_BYTES and row.meta["text_truncated"] is True
