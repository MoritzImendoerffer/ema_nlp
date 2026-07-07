"""Unit tests for harness.retrieval.doc_categories (source-category classifier)."""

import pytest

from harness.retrieval.doc_categories import CATEGORIES, classify_source


@pytest.mark.parametrize(
    "url,expected",
    [
        # Q&A pages/documents (incl. Q&A *about* guidelines — qa outranks guideline)
        ("https://www.ema.europa.eu/en/human-regulatory-overview/post-authorisation/"
         "variations-including-extensions-marketing-authorisations/worksharing-questions-answers", "qa"),
        ("https://www.ema.europa.eu/en/documents/other/questions-answers-implementation-ich-q3d_en.pdf", "qa"),
        # Scientific / procedural guidelines
        ("https://www.ema.europa.eu/en/documents/scientific-guideline/ich-q3a-r2_en.pdf", "scientific_guideline"),
        ("https://www.ema.europa.eu/en/human-regulatory-overview/research-development/"
         "scientific-guidelines/quality-guidelines", "scientific_guideline"),
        ("https://www.ema.europa.eu/en/documents/regulatory-procedural-guideline/x_en.pdf", "scientific_guideline"),
        # EPAR assessment reports vs medicine overview pages
        ("https://www.ema.europa.eu/en/documents/assessment-report/keytruda-epar-public-assessment-report_en.pdf", "epar"),
        ("https://www.ema.europa.eu/en/medicines/human/EPAR/keytruda", "medicine_page"),
        # Neither
        ("https://www.ema.europa.eu/en/human-regulatory-overview/medical-devices/"
         "consultation-procedure-ancillary-medicinal-substances-medical-devices", "other"),
        ("", "other"),
    ],
)
def test_classify_source_url_shapes(url, expected):
    assert classify_source(url) == expected


def test_topic_path_alone_classifies():
    assert classify_source("", "/human-regulatory-overview/x/questions-answers-article-30/") == "qa"


def test_all_outputs_are_canonical_categories():
    urls = [
        "https://www.ema.europa.eu/en/documents/scientific-guideline/a.pdf",
        "https://www.ema.europa.eu/en/medicines/human/EPAR/b",
        "https://example.org/unrelated",
    ]
    for u in urls:
        assert classify_source(u) in CATEGORIES
