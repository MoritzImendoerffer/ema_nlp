"""The docling parser in the retrieval environment (work unit 28, TASK-004).

Docling is not installed in .venv, and must not be (it would move the embedding model's
torch). Here the parser must answer with `missing_extra`, never raise, and import nothing
heavy. Its real runs are in tests/test_docling_parse_env.py (`make test-parse`).
"""

from __future__ import annotations

import importlib.util

import pytest

from corpus.parsers.base import Parser
from corpus.parsers.docling_pdf import OPTIONS, OPTIONS_HASH, DoclingPdfParser

_URL = "https://www.ema.europa.eu/en/documents/scientific-guideline/x_en.pdf"


@pytest.mark.skipif(importlib.util.find_spec("docling") is not None, reason="docling is installed here")
def test_missing_extra_in_retrieval_env():
    doc = DoclingPdfParser().parse(b"%PDF-1.5", url=_URL)
    assert doc.error.startswith("missing_extra")
    assert doc.text == "" and doc.parser == "docling"
    assert doc.parser_version.endswith("+" + OPTIONS_HASH)


def test_protocol_and_options():
    assert isinstance(DoclingPdfParser(), Parser)
    assert len(OPTIONS_HASH) == 8
    assert OPTIONS["ocr"]["recognizer"] == "PP-OCRv6 medium"
    assert OPTIONS["ocr"]["detector"] == "PP-OCRv6 small"


def test_module_imports_no_docling():
    import sys

    assert "docling" not in sys.modules or importlib.util.find_spec("docling") is not None
