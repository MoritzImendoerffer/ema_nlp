"""Source-category classification for EMA documents (pure, table-driven).

There is no first-class document-type property on the retrievable graph nodes
(``document_type`` exists only on ``LINKS_TO`` edges), so the category is derived
from the document's URL / topic path. Categories power the reference cards, the
export renderers, the SME "wrong source type — prefer <category>" feedback, and
the ``doc_type_priority`` postprocessor.

The rules are ordered, first match wins, and deliberately simple substring
checks over the lowered URL+topic string — extend ``_RULES`` when a new EMA URL
shape shows up. Everything here is offline-testable.
"""

from __future__ import annotations

# Canonical categories, most-authoritative-first (the default priority the
# doc_type_priority postprocessor uses when a recipe doesn't override it).
CATEGORIES = (
    "scientific_guideline",
    "qa",
    "epar",
    "medicine_page",
    "other",
)

# Ordered (category, [substring, ...]) rules over lower(source_url + " " + topic_path).
# First rule with any matching substring wins. Q&A outranks guideline because EMA
# publishes Q&A documents *about* guidelines under guideline-ish paths.
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("qa", ("questions-answers", "q-and-a", "questions-and-answers")),
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
        ),
    ),
    ("medicine_page", ("/medicines/human/epar/", "/medicines/human/")),
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
