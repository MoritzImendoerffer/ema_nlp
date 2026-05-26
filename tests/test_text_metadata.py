"""Tests for corpus/metadata/text_metadata.py.

The regexes are lifted verbatim from ``corpus/ingestion/pdf_normaliser.py``
(re-exported there for back-compat) so existing pdf_normaliser tests still
pass. The cases here lock in:

  * The five-field happy path on the existing markdown fixture.
  * Graceful degradation (None per field, no exception) when fields are
    absent — including a synthetic no-H1, no-ref, malformed-date sample.
  * Parity with what ``pdf_normaliser.normalise_pdf_doc`` extracts on the
    same input (golden cross-check).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from corpus.ingestion.pdf_normaliser import normalise_pdf_doc
from corpus.metadata.text_metadata import (
    EMA_REF_RE,
    TextMetadata,
    text_metadata,
)

FIXTURES = Path(__file__).parent / "fixtures"
PDF_SAMPLE_MD = (FIXTURES / "ema_pdf_sample.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Happy path — fixture
# ---------------------------------------------------------------------------


def test_returns_text_metadata_instance() -> None:
    assert isinstance(text_metadata("# T\n\nbody"), TextMetadata)


def test_extracts_title_from_h1():
    md = "# Questions and answers on benzene impurities\n\nBody"
    out = text_metadata(md)
    assert out.title == "Questions and answers on benzene impurities"


def test_extracts_all_fields_from_full_header():
    md = (
        "EMA/CHMP/508188/2013 Rev. 2 adopted 21 March 2024\n\n"
        "# Questions and answers on benzyl alcohol\n\n"
        "Body text here."
    )
    out = text_metadata(md)
    assert out.title == "Questions and answers on benzyl alcohol"
    assert out.reference_number == "EMA/CHMP/508188/2013"
    assert out.committee == "CHMP"
    assert out.revision == "2"
    assert out.last_updated == datetime(2024, 3, 21, tzinfo=UTC)


def test_revision_word_form():
    md = "EMA/PRAC/100/2021 Revision 4\n\n# Foo\n\nBody"
    out = text_metadata(md)
    assert out.revision == "4"
    assert out.committee == "PRAC"


def test_unknown_committee_letters_normalise_to_none():
    md = "EMA/XYZ/1234/2024\n\n# Title\n\nBody"
    out = text_metadata(md)
    assert out.reference_number == "EMA/XYZ/1234/2024"
    assert out.committee is None


def test_fixture_pdf_sample_md_title():
    out = text_metadata(PDF_SAMPLE_MD)
    assert out.title == "Questions and answers on benzene impurities"
    # Fixture has no EMA ref, no revision, no date
    assert out.reference_number is None
    assert out.committee is None
    assert out.revision is None
    assert out.last_updated is None


# ---------------------------------------------------------------------------
# Parity with the legacy pdf_normaliser on real Mongo-shape docs
# ---------------------------------------------------------------------------


def test_parity_with_pdf_normaliser_on_fixture():
    legacy = normalise_pdf_doc(
        {"_id": "https://x.test/example.pdf", "markdown": PDF_SAMPLE_MD, "error": ""}
    )
    new = text_metadata(PDF_SAMPLE_MD)
    assert legacy is not None
    assert new.title == legacy.title
    assert new.reference_number == legacy.reference_number
    assert new.committee == legacy.committee
    assert new.revision == legacy.revision
    assert new.last_updated == legacy.last_updated


def test_parity_with_pdf_normaliser_on_full_header():
    md = (
        "EMA/CHMP/508188/2013 Rev. 2 adopted 21 March 2024\n\n"
        "# Questions and answers on benzyl alcohol\n\n"
        "Body text here." * 5
    )
    legacy = normalise_pdf_doc({"_id": "https://x.test/qa.pdf", "markdown": md, "error": ""})
    new = text_metadata(md)
    assert legacy is not None
    assert new.title == legacy.title
    assert new.reference_number == legacy.reference_number
    assert new.committee == legacy.committee
    assert new.revision == legacy.revision
    assert new.last_updated == legacy.last_updated


# ---------------------------------------------------------------------------
# Graceful degradation — no exception when fields are missing/malformed
# ---------------------------------------------------------------------------


def test_no_h1_returns_none_title():
    md = "EMA/CHMP/100/2024\n\nNo header here, just prose."
    out = text_metadata(md)
    assert out.title is None
    # Ref still found
    assert out.reference_number == "EMA/CHMP/100/2024"


def test_no_reference_returns_none_ref_and_committee():
    md = "# Some title\n\nNo EMA reference in this body."
    out = text_metadata(md)
    assert out.reference_number is None
    assert out.committee is None


def test_malformed_date_returns_none_last_updated():
    md = "# Title\n\nadopted 32 Smarch 9999"  # invalid month + day
    out = text_metadata(md)
    assert out.last_updated is None


def test_empty_text_does_not_raise():
    out = text_metadata("")
    assert out.title is None
    assert out.reference_number is None
    assert out.committee is None
    assert out.revision is None
    assert out.last_updated is None


def test_emits_debug_log_when_field_missing(caplog):
    with caplog.at_level(logging.DEBUG, logger="corpus.metadata.text_metadata"):
        text_metadata("")
    messages = [r.message for r in caplog.records]
    assert any("metadata missing: title" in m for m in messages)
    assert any("metadata missing: reference_number" in m for m in messages)
    assert any("metadata missing: last_updated" in m for m in messages)


# ---------------------------------------------------------------------------
# Regex sanity
# ---------------------------------------------------------------------------


def test_ema_ref_regex_matches_canonical_form():
    assert EMA_REF_RE.search("see EMA/CHMP/12345/2023 for details")
    assert EMA_REF_RE.search("EMA/PRAC/CHMP/99/2024 mixed")
    assert not EMA_REF_RE.search("EMA/12/2024")
