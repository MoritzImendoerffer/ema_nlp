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
        # Human-regulatory topic pages (formerly "other")
        ("https://www.ema.europa.eu/en/human-regulatory-overview/medical-devices/"
         "consultation-procedure-ancillary-medicinal-substances-medical-devices", "regulatory_overview"),
        # Procedure outputs (PIP / orphan / PSUSA / referral / SMOP / DHPC / PRAC)
        ("https://www.ema.europa.eu/en/documents/pip-decision/p-0123-2020_en.pdf", "regulatory_procedure"),
        ("https://www.ema.europa.eu/en/documents/orphan-designation/eu-3-20-2222_en.pdf", "regulatory_procedure"),
        ("https://www.ema.europa.eu/en/documents/psusa/x_en.pdf", "regulatory_procedure"),
        ("https://www.ema.europa.eu/en/documents/referral/nitrosamines-article-53-referral_en.pdf", "regulatory_procedure"),
        ("https://www.ema.europa.eu/en/documents/prac-recommendation/signal-x_en.pdf", "regulatory_procedure"),
        # Meeting material, slides, announcements
        ("https://www.ema.europa.eu/en/documents/agenda/agenda-chmp-meeting-2024_en.pdf", "meeting_doc"),
        ("https://www.ema.europa.eu/en/documents/minutes/minutes-prac-meeting_en.pdf", "meeting_doc"),
        ("https://www.ema.europa.eu/en/documents/presentation/presentation-x_en.pdf", "presentation"),
        ("https://www.ema.europa.eu/en/news/ema-recommends-approval-of-x", "news"),
        ("https://www.ema.europa.eu/en/documents/press-release/x_en.pdf", "news"),
        # Reference + domain families
        ("https://www.ema.europa.eu/en/glossary-terms/acceptable-intake", "glossary"),
        ("https://www.ema.europa.eu/en/documents/herbal-monograph/final-monograph-x_en.pdf", "herbal"),
        ("https://www.ema.europa.eu/en/medicines/herbal/valerianae-radix", "herbal"),
        # Veterinary trumps everything (human-only benchmark → must stay filterable)
        ("https://www.ema.europa.eu/en/documents/mrl-report/x-summary-report_en.pdf", "veterinary"),
        ("https://www.ema.europa.eu/en/medicines/veterinary/EPAR/simparica-trio", "veterinary"),
        ("https://www.ema.europa.eu/en/veterinary-regulatory-overview/x-questions-answers", "veterinary"),
        # EPAR family additions
        ("https://www.ema.europa.eu/en/documents/scientific-conclusion/x_en.pdf", "epar"),
        # Neither
        ("https://www.ema.europa.eu/en/documents/procurement/tender-x_en.pdf", "other"),
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
