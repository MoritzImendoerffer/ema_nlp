"""Source-category classification for EMA documents (pure, table-driven).

There is no first-class document-type property on the retrievable graph nodes
(``document_type`` exists only on ``LINKS_TO`` edges), so the category is derived
from the document's URL / topic path. Categories power the reference cards, the
export renderers, the SME "wrong source type — prefer <category>" feedback, and
the ``doc_type_priority`` postprocessor.

The vocabulary groups EMA's own URL taxonomy (the ``/en/documents/<type>/``
segment, cross-checked against the sitemap + the live corpus distribution,
2026-07-12): with only the original five categories, 63% of the 79,882 indexed
docs fell into ``other``; the families below take that to ~10%.

The rules are ordered, first match wins, and deliberately simple substring
checks over the lowered URL+topic string — extend ``_RULES`` when a new EMA URL
shape shows up. Everything here is offline-testable.
"""

from __future__ import annotations

# Canonical categories, most-authoritative-first for human-regulatory Q&A (the
# default priority the doc_type_priority postprocessor uses when a recipe
# doesn't override it). Roughly: general rules (guidelines/Q&A/topic overviews)
# > product evidence (EPAR/medicine pages/procedure outputs) > reference &
# meeting material > announcements/slides > out-of-scope (veterinary).
CATEGORIES = (
    "scientific_guideline",
    "qa",
    "regulatory_overview",  # /human-regulatory-overview topic + procedure pages
    "epar",
    "medicine_page",
    "regulatory_procedure",  # PIP / orphan / PSUSA / referral / SMOP / withdrawal / DHPC
    "herbal",  # HMPC monograph family
    "glossary",
    "meeting_doc",  # agendas / minutes / committee reports
    "news",  # news, events, press releases, newsletters, public statements
    "presentation",  # slide decks
    "veterinary",  # CVMP / MRL / vet pages — out of benchmark scope, filterable
    "other",
)

# Ordered (category, [substring, ...]) rules over lower(source_url + " " + topic_path).
# First rule with any matching substring wins. Ordering notes:
#   - veterinary is FIRST: for a human-only benchmark, vet content must stay
#     filterable even when it is also a Q&A/guideline/news page.
#   - qa outranks guideline because EMA publishes Q&A documents *about*
#     guidelines under guideline-ish paths.
#   - epar outranks regulatory_procedure so the ``-epar-`` document family
#     (variation reports, procedural steps, scientific conclusions, ...) stays
#     together regardless of its /documents/<type>/ segment.
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("veterinary", ("veterinary", "/documents/mrl-")),
    ("qa", ("questions-answers", "q-and-a", "questions-and-answers", "/documents/medicine-qa/")),
    ("herbal", ("/documents/herbal-", "/medicines/herbal")),
    (
        "scientific_guideline",
        (
            "/documents/scientific-guideline/",
            "/scientific-guidelines/",
            "/documents/regulatory-procedural-guideline/",
            "guideline",
        ),
    ),
    (
        "epar",
        (
            "/documents/assessment-report/",
            "epar-public-assessment-report",
            "-epar-",
            "/documents/chmp-annex/",
            "/documents/scientific-conclusion",
        ),
    ),
    (
        "regulatory_procedure",
        (
            "/documents/pip-",  # pip-decision / -discontinuation / -summary
            "/documents/orphan-",  # orphan-designation / -maintenance-report / -review
            "/documents/psusa/",
            "/medicines/psusa",
            "/documents/referral/",
            "/documents/smop",
            "/documents/withdrawal-",
            "/documents/dhpc/",
            "/medicines/dhpc",
            "/documents/prac-recommendation",
        ),
    ),
    (
        "meeting_doc",
        (
            "/documents/agenda/",
            "/documents/minutes/",
            "/documents/committee-report/",
            "/documents/work-programme",
        ),
    ),
    ("presentation", ("/documents/presentation/",)),
    (
        "news",
        (
            "/en/news",
            "/en/events",
            "/documents/press-release/",
            "/documents/newsletter/",
            "/documents/public-statement/",
        ),
    ),
    ("glossary", ("/glossary-terms",)),
    ("regulatory_overview", ("/human-regulatory-overview",)),
    ("medicine_page", ("/medicines/human/epar/", "/medicines/human/", "/en/medicines/")),
)


def classify_source(source_url: str = "", topic_path: str = "") -> str:
    """Best-effort category for a source document.

    Returns one of :data:`CATEGORIES`; ``"other"`` when nothing matches or both
    inputs are empty.
    """
    haystack = f"{source_url or ''} {topic_path or ''}".lower()
    if not haystack.strip():
        return "other"
    for category, needles in _RULES:
        if any(needle in haystack for needle in needles):
            return category
    return "other"
