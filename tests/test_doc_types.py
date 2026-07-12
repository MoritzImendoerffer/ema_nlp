"""Unit tests for harness.indexing.doc_types (EMA JSON export → doc_type join)."""

from harness.indexing.chunking import doc_id_for
from harness.indexing.doc_types import parse_document_types

# Mirrors the real export's quirks: records separated by WHITESPACE not commas,
# and a `name` with an unescaped inner quote — a whole-file json.loads would fail.
_EXPORT = """
{
"meta": {"total_records": 3},
"data": [
    {"id":"1","name":"Keytruda EPAR","type":"assessment-report","document_url":"https://www.ema.europa.eu/en/documents/assessment-report/keytruda_en.pdf"}
    {"id":"2","name":"A \\"quoted\\" and , comma name","type":"product-information","document_url":"https://www.ema.europa.eu/en/documents/product-information/keytruda-epar-product-information_en.pdf"}
    {"id":"3","name":"No url record","type":"agenda"}
]
}
"""


def test_parses_type_by_doc_id_despite_malformed_json():
    got = parse_document_types(_EXPORT)
    url1 = "https://www.ema.europa.eu/en/documents/assessment-report/keytruda_en.pdf"
    url2 = "https://www.ema.europa.eu/en/documents/product-information/keytruda-epar-product-information_en.pdf"
    assert got[doc_id_for(url1)] == "assessment-report"
    assert got[doc_id_for(url2)] == "product-information"


def test_records_without_url_are_skipped():
    # only the two records carrying a document_url survive
    assert len(parse_document_types(_EXPORT)) == 2


def test_missing_type_is_empty_string():
    export = (
        '{"data":['
        '{"id":"9","document_url":"https://www.ema.europa.eu/en/documents/other/x_en.pdf"}'
        "]}"
    )
    url = "https://www.ema.europa.eu/en/documents/other/x_en.pdf"
    assert parse_document_types(export) == {doc_id_for(url): ""}


def test_empty_input():
    assert parse_document_types("") == {}
    assert parse_document_types('{"data":[]}') == {}


def test_duplicate_url_last_type_wins():
    url = "https://www.ema.europa.eu/en/documents/report/x_en.pdf"
    export = (
        f'{{"data":[{{"type":"report","document_url":"{url}"}} '
        f'{{"type":"overview","document_url":"{url}"}}]}}'
    )
    assert parse_document_types(export) == {doc_id_for(url): "overview"}
