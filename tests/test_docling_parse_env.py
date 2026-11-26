"""Tests that run in the Docling parse environment only (`make test-parse`), never in the gate.

The gate deselects them by marker (`make test`: `-m "not integration and not parse"`), and
each skips when Docling is not importable, so a plain `pytest` in .venv stays green.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.parse

docling = pytest.importorskip("docling")


def test_pinned_versions():
    from importlib.metadata import version

    assert version("docling") == "2.153.0"
    assert version("rapidocr") == "3.10.0"
    assert version("torch").startswith("2.15.0")


def test_retrieval_env_is_not_this_env():
    import sys

    assert ".venv" not in sys.prefix.split("/")


_FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures" / "docling"


@pytest.mark.gpu
def test_table_stage_reads_a_table():
    """TASK-003: the stage, registered in code, reads a ruled 3x3 table into 9 cells."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    from corpus.parsers.paddleocr_vl_table import PaddleOcrVlTableOptions, register

    register()
    register()  # idempotent
    opts = PdfPipelineOptions(allow_external_plugins=True, do_ocr=False,
                              table_structure_options=PaddleOcrVlTableOptions())
    conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    doc = conv.convert(str(_FIXTURES / "table_3x3.pdf")).document
    assert len(doc.tables) == 1
    table = doc.tables[0]
    assert (table.data.num_rows, table.data.num_cols) == (3, 3)
    texts = {c.text.strip() for c in table.data.table_cells}
    assert {"Age group", "12.5", "twice daily"} <= texts


@pytest.mark.gpu
def test_parser_on_fixture_pdf():
    """TASK-004: the parser with the plan's options parses a real PDF to SUCCESS."""
    from corpus.parsers.docling_pdf import DoclingPdfParser, prefetch

    prefetch()
    pdf = (__import__("pathlib").Path(__file__).parent / "fixtures" / "fixture_pdf_0.pdf").read_bytes()
    doc = DoclingPdfParser().parse(pdf, url="https://www.ema.europa.eu/en/documents/x/fixture_en.pdf")
    assert doc.error == ""
    assert doc.meta["pages"] > 0 and len(doc.text) > 1000
    assert doc.parser_version.startswith("2.153.0+")


@pytest.mark.gpu
def test_parser_reads_the_table_fixture_and_gzip():
    import gzip

    from corpus.parsers.docling_pdf import convert_pdf

    raw = (_FIXTURES / "table_3x3.pdf").read_bytes()
    plain, packed = convert_pdf(raw), convert_pdf(gzip.compress(raw))
    assert plain.status == "SUCCESS" and plain.counts["tables"] == 1 and plain.counts["cells"] == 9
    assert packed.status == "SUCCESS" and packed.markdown == plain.markdown


def test_ocr_uses_the_medium_recognizer():
    from corpus.parsers.docling_pdf import (
        REC_MEDIUM_SHA256,
        _sha256,
        build_converter,
        fetch_rec_model,
    )

    path = fetch_rec_model()
    assert _sha256(path) == REC_MEDIUM_SHA256
    conv = build_converter()
    from docling.datamodel.base_models import InputFormat

    opts = conv.format_to_options[InputFormat.PDF].pipeline_options
    assert opts.ocr_options.rec_model_path == str(path) and opts.ocr_options.model_size == "small"
