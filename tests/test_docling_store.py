"""The stored shape of a Docling parse (work unit 28, TASK-001)."""

from __future__ import annotations

import hashlib
from pathlib import Path

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
