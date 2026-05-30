"""Link extractor — ``links_to`` edges from raw HTML.

This is the extractor MIGR-018..025 described but never shipped (see work unit
19). It parses ``<a href>`` anchors out of a page's HTML, resolves relative
URLs against the page URL, drops non-navigational links, and classifies each
target as ``file`` (downloadable doc), ``page`` (same-domain HTML), or
``external``. The ingestion layer (LIR-006) turns these into ``links_to`` edges
between document nodes (resolved via ``sha256(url)``).
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from harness.indexing.chunking import doc_id_for

_FILE_EXTS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".csv")
_SKIP_SCHEMES = ("mailto:", "tel:", "javascript:")
ALLOWED_DOMAINS = ("ema.europa.eu",)


@dataclass(frozen=True)
class ExtractedLink:
    tgt_url: str
    anchor: str
    kind: str  # "file" | "page" | "external"

    @property
    def tgt_doc_id(self) -> str:
        return doc_id_for(self.tgt_url)


def _strip_fragment(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, p.query, ""))


def _classify(url: str, allowed_domains: tuple[str, ...]) -> str:
    parts = urlsplit(url)
    if any(parts.path.lower().endswith(ext) for ext in _FILE_EXTS):
        return "file"
    host = parts.netloc.lower()
    if any(host == d or host.endswith("." + d) for d in allowed_domains):
        return "page"
    return "external"


def extract_links(
    html: str,
    base_url: str,
    *,
    allowed_domains: tuple[str, ...] = ALLOWED_DOMAINS,
) -> list[ExtractedLink]:
    """Return de-duplicated outgoing links from ``html`` (anchored at ``base_url``)."""
    soup = BeautifulSoup(html or "", "lxml")
    base_norm = _strip_fragment(base_url)
    seen: set[str] = set()
    out: list[ExtractedLink] = []
    for a in soup.find_all("a", href=True):
        href = (a["href"] or "").strip()
        if not href or href.startswith("#"):
            continue
        if any(href.lower().startswith(s) for s in _SKIP_SCHEMES):
            continue
        tgt = _strip_fragment(urljoin(base_url, href))
        if not urlsplit(tgt).scheme.startswith("http"):
            continue
        if tgt == base_norm or tgt in seen:  # self-reference / duplicate
            continue
        seen.add(tgt)
        out.append(
            ExtractedLink(tgt_url=tgt, anchor=a.get_text(strip=True)[:200],
                          kind=_classify(tgt, allowed_domains))
        )
    return out
