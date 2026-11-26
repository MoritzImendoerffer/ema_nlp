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


def test_post_processed_document_loads_in_docling_core():
    """The joined document is still a valid DoclingDocument and renders to Markdown."""
    import json

    from docling_core.types.doc import DoclingDocument

    from corpus.parsers.docling_post import post_process

    raw = json.loads((_FIXTURES / "trepulmix_procedural_steps.raw.json").read_text())
    doc, counts = post_process(raw)
    loaded = DoclingDocument.model_validate(doc)
    assert counts["tables_joined"] == 3 and len(loaded.tables) == 1
    assert loaded.tables[0].data.num_rows == 16
    assert "Application number" in loaded.export_to_markdown()


def test_attached_footnotes_load_in_docling_core():
    from docling_core.types.doc import DoclingDocument

    from corpus.parsers.docling_post import post_process
    from tests.test_docling_post import _doc, _table, _text

    doc = _doc(["#/tables/0", "#/texts/0"], [_table(0, 1, [["Set", "n"], [r"FAS\(^{a}\)", "120"]])],
               texts=[_text(0, 1, "a Full analysis set.")])
    out, counts = post_process(doc)
    loaded = DoclingDocument.model_validate(out)
    assert counts["footnotes_attached"] == 1
    assert loaded.tables[0].footnotes[0].cref == "#/texts/0"
    md = loaded.export_to_markdown()
    assert "FAS[^a]" in md and "[^a]: Full analysis set." in md


def test_marked_number_stays_a_number_in_the_markdown_after_normalisation():
    """Lead session's review of 2026-11-26: the Markdown, after NFKC and after NFKD, still holds
    12.5 and 3.2 as numbers of their own, never 12.51 or 3.2a."""
    import re
    import unicodedata

    from docling_core.types.doc import DoclingDocument

    from corpus.parsers.docling_post import post_process
    from tests.test_docling_post import _doc, _table, _text

    doc = _doc(["#/tables/0", "#/texts/0"], [_table(0, 1, [["Dose", "Ratio"], [r"12.5\(^{1}\)", "3.2ᵃ"]])],
               texts=[_text(0, 1, "1 Given with food.")])
    out, _ = post_process(doc)
    md = DoclingDocument.model_validate(out).export_to_markdown()
    for form in ("NFKC", "NFKD"):
        numbers = re.findall(r"\d+(?:\.\d+)?", unicodedata.normalize(form, md))
        assert "12.5" in numbers and "3.2" in numbers
        assert "12.51" not in numbers and "3.2a" not in unicodedata.normalize(form, md)


def test_lifted_header_reference_heads_the_markdown():
    from docling_core.types.doc import DoclingDocument

    from corpus.metadata.text_metadata import text_metadata
    from corpus.parsers.docling_post import post_process
    from tests.test_docling_post import _doc, _text

    texts = [_text(0, 1, "EMA/CHMP/123456/2020 Rev. 1", "page_header", "furniture"),
             _text(1, 1, "Guideline on the investigation of bioequivalence", "title"),
             _text(2, 1, "This guideline specifies the requirements.")]
    out, counts = post_process(_doc(["#/texts/0", "#/texts/1", "#/texts/2"], [], texts=texts))
    md = DoclingDocument.model_validate(out).export_to_markdown()
    assert counts["header_reference_lifted"] == 1
    assert md.lstrip().startswith("EMA/CHMP/123456/2020")
    assert text_metadata(md).reference_number == "EMA/CHMP/123456/2020"
