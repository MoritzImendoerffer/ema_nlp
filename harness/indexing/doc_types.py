"""EMA document-type join — authoritative ``type`` per PDF from the website JSON.

The retrievable graph has no first-class document-type on PDF nodes: the
``category`` in ``harness.retrieval.doc_categories`` is derived from the URL, and
the finer ``document_type`` only ever existed on ``LINKS_TO`` file-card edges
(so a PDF reachable by no card had none). EMA publishes the missing label
itself: the website-data export at

    https://www.ema.europa.eu/en/about-us/about-website/download-website-data-json-data-format

lists every published document with a curated ``type`` (85 values —
``assessment-report``, ``product-information``, ``scientific-guideline``, ...),
keyed by ``document_url``. Hashing that URL with ``doc_id_for`` joins it to our
``:Document.id``: measured 2026-07-12, the ``documents`` export covers 96.6% of
our 57,925 PDF nodes (HTML pages are not in this export — they carry the
``ema-bg-*`` badges instead; see ``harness.indexing.badges``). The parsed map
is persisted per-URL in Mongo ``document_metadata``
(``harness.indexing.document_metadata``, written by
``scripts/enrich_document_metadata.py``) and joined at ingest / propagated to
an existing graph from there.

The export is *almost* JSON but ships malformed: array elements are separated by
whitespace instead of commas, and some ``name`` values contain unescaped quotes
/ control chars, so a whole-file ``json.loads`` fails. We only need two
quote-free fields (``document_url``, ``type``) per record, so we brace-split the
file and regex those out — immune to the string-escaping breakage.
"""

from __future__ import annotations

import re

DOCUMENTS_JSON_URL = (
    "https://www.ema.europa.eu/en/documents/report/documents-output-json-report_en.json"
)

_RECORD_RE = re.compile(r"\{[^{}]*\}")
_URL_RE = re.compile(r'"document_url"\s*:\s*"([^"]*)"')
_TYPE_RE = re.compile(r'"type"\s*:\s*"([^"]*)"')


def parse_document_types_by_url(raw: str) -> dict[str, str]:
    """Map ``document_url -> type`` from the raw EMA documents JSON export text.

    Tolerant of the export's malformed structure (see module docstring). Records
    without a ``document_url`` are skipped; on a duplicate URL the last type
    wins. ``type`` may be an empty string when the export omits it. Hash the URL
    with ``doc_id_for`` when a ``:Document.id``-keyed map is needed.
    """
    out: dict[str, str] = {}
    for rec in _RECORD_RE.findall(raw):
        m_url = _URL_RE.search(rec)
        if not m_url:
            continue
        url = m_url.group(1).strip()
        if not url:
            continue
        m_type = _TYPE_RE.search(rec)
        out[url] = m_type.group(1).strip() if m_type else ""
    return out
