"""Extract outgoing links from EMA narrative documents.

Four extractors, all return ``list[Link]``:

    extract_from_markdown(md)              [text](url) → link_type='hyperlink'
    extract_from_html(html, base_url)      <a href> → link_type='hyperlink'
    extract_reference_numbers(text)        EMA/.../YYYY → link_type='reference_number'
    extract_see_qa(text)                   'see Q&A 5' / 'see question 5' → link_type='see_qa'

The ``tgt_url`` field carries:
    * fully qualified URL (hyperlink) — relative paths are resolved against
      ``base_url`` for the HTML extractor; the markdown extractor only matches
      already-absolute http(s) URLs.
    * the raw reference code as the URL slot for reference_number links
      (resolved to a doc_id later by scripts/resolve_links.py).
    * the literal matched 'see Q&A N' / 'see question N' string for see_qa links
      (best-effort metadata; not currently resolved).

Empty results are common — many EMA pages are navigation chrome with no
narrative content. Dedup is the caller's job (the ON CONFLICT clause on
``links`` swallows duplicates).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from corpus.metadata.text_metadata import EMA_REF_RE

LinkType = Literal["hyperlink", "reference_number", "see_qa"]


@dataclass(frozen=True)
class Link:
    tgt_url: str
    link_type: LinkType
    anchor: str | None = None


_MD_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_SEE_QA_RE = re.compile(
    r"\b(?:see\s+(?:Q\s*&\s*A|Q\s*and\s*A)\s*(?:no\.?|number)?\s*(\d+)"
    r"|see\s+question\s+(?:no\.?|number)?\s*(\d+))",
    flags=re.IGNORECASE,
)

_SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "blob:")


def _norm_anchor(text: str | None) -> str | None:
    if not text:
        return None
    out = re.sub(r"\s+", " ", text).strip()
    return out or None


def _is_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def extract_from_markdown(md: str) -> list[Link]:
    """Pull ``[text](http(s)://...)`` links from markdown text."""
    if not md:
        return []
    out: list[Link] = []
    for m in _MD_LINK_RE.finditer(md):
        anchor = _norm_anchor(m.group(1))
        url, _frag = urldefrag(m.group(2))
        if not _is_http_url(url):
            continue
        out.append(Link(tgt_url=url, link_type="hyperlink", anchor=anchor))
    return out


def extract_from_html(html: str, base_url: str) -> list[Link]:
    """Pull anchor links from HTML, resolving relative URLs against ``base_url``.

    Skips:
        * non-http(s) schemes (mailto, tel, javascript, data, blob)
        * pure-fragment links (#section)
        * links that resolve back to ``base_url`` exactly (self-references)
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    out: list[Link] = []
    base_clean, _ = urldefrag(base_url)
    for a in soup.find_all("a", href=True):
        href_raw = (a.get("href") or "").strip()
        if not href_raw:
            continue
        lower = href_raw.lower()
        if any(lower.startswith(s) for s in _SKIP_SCHEMES):
            continue
        if href_raw.startswith("#"):
            continue
        absolute, _frag = urldefrag(urljoin(base_url, href_raw))
        if not _is_http_url(absolute):
            continue
        if absolute == base_clean:
            continue
        anchor = _norm_anchor(a.get_text(" ", strip=True))
        out.append(Link(tgt_url=absolute, link_type="hyperlink", anchor=anchor))
    return out


def extract_reference_numbers(text: str) -> list[Link]:
    """Pull EMA/.../YYYY style reference codes from text as link_type='reference_number'.

    The matched string is placed in ``tgt_url`` for later resolution; the anchor
    field is left None (no surrounding context captured here)."""
    if not text:
        return []
    seen: set[str] = set()
    out: list[Link] = []
    for m in EMA_REF_RE.finditer(text):
        code = m.group(0)
        if code in seen:
            continue
        seen.add(code)
        out.append(Link(tgt_url=code, link_type="reference_number", anchor=None))
    return out


def extract_see_qa(text: str) -> list[Link]:
    """Pull 'see Q&A N' / 'see question N' references."""
    if not text:
        return []
    out: list[Link] = []
    for m in _SEE_QA_RE.finditer(text):
        n = m.group(1) or m.group(2)
        if not n:
            continue
        marker = m.group(0)
        out.append(Link(tgt_url=f"qa:{n}", link_type="see_qa", anchor=_norm_anchor(marker)))
    return out


def extract_all(
    *,
    markdown: str | None = None,
    html: str | None = None,
    base_url: str | None = None,
) -> list[Link]:
    """Convenience: run every extractor that has an input available.

    ``markdown`` covers hyperlink + reference_number + see_qa over the rendered
    text. ``html`` (with ``base_url``) adds the structural <a href> hyperlinks
    that may not have survived the markdown conversion. Caller is responsible
    for deduplication if both inputs are supplied (the ON CONFLICT clause on
    the ``links`` table handles it at the DB layer).
    """
    out: list[Link] = []
    if markdown:
        out.extend(extract_from_markdown(markdown))
        out.extend(extract_reference_numbers(markdown))
        out.extend(extract_see_qa(markdown))
    if html and base_url:
        out.extend(extract_from_html(html, base_url))
    return out
