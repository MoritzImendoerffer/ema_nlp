"""Link extractor — typed ``links_to`` edges from the page's main content.

Ported (not imported) from ``ema_scraper/parsers/ema_parser.py`` (``EmaPageParser``):
extraction is scoped to ``<main class="main-content-wrapper">`` and is BCL-component
aware, so the global header/footer/mega-menu chrome never becomes a link. Parsing
whole pages turned ~95% of the live ``LINKS_TO`` edge set into site-nav boilerplate
(74 chrome targets absorbed 94.4% of 1.72M edges); main-content scoping removes that
at the source — see ``docs/RETRIEVAL_TRACKS.md`` §0.8 and the work unit
``2026-05-30_20`` / ``2026-06-04_24``.

Each anchor is classified two ways:
  - ``kind``         — by URL shape: ``file`` (downloadable doc) / ``page`` (same-domain
                       HTML) / ``external`` (URL normalization is unchanged from before).
  - ``link_context`` — by the DOM component it was found in: ``file_component`` (a
                       ``.bcl-file`` document card, which also carries ``document_type``),
                       ``card_or_listing`` (``.bcl-listing`` / ``.listing-item`` /
                       ``.bcl-content-banner``), ``inline`` (paragraph / heading / list /
                       table / accordion-body / alert text), or ``other`` (a standalone
                       anchor in a generic container).

The ingestion layer turns these into ``LINKS_TO`` edges between document nodes
(resolved via ``sha256(url)``), stamping ``{kind, link_context, document_type, anchor}``
as edge properties.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from harness.indexing.chunking import doc_id_for

_log = logging.getLogger(__name__)

_FILE_EXTS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".csv")
_SKIP_SCHEMES = ("mailto:", "tel:", "javascript:")
ALLOWED_DOMAINS = ("ema.europa.eu",)

# ── DOM scoping (ported from EmaPageParser) ─────────────────────────────────
MAIN_SELECTOR_CLASS = "main-content-wrapper"
_SKIP_TAGS = {"script", "style", "noscript", "svg", "button", "form", "input"}
_SKIP_CLASSES = {"bcl-inpage-navigation", "breadcrumb", "dropdown-menu"}
# text blocks: every <a> inside is an inline link (find_all, then stop recursing)
_TEXT_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "dd", "dt", "td", "th",
              "blockquote", "ul", "ol", "dl", "table"}
# containers we recurse into to find nested content (links can sit arbitrarily deep)
_CONTAINER_TAGS = {"div", "section", "article", "main", "aside", "header", "footer", "span"}

_FILE_COMPONENT = "file_component"
_CARD_OR_LISTING = "card_or_listing"
_INLINE = "inline"
_OTHER = "other"
LINK_CONTEXTS = (_FILE_COMPONENT, _CARD_OR_LISTING, _INLINE, _OTHER)
# de-dup priority: a target seen as a file card beats one seen inline/standalone
_CONTEXT_PRIORITY = {_FILE_COMPONENT: 3, _CARD_OR_LISTING: 2, _INLINE: 1, _OTHER: 0}
_CARD_CLASSES = {"bcl-listing", "listing-item", "bcl-content-banner"}


@dataclass(frozen=True)
class ExtractedLink:
    tgt_url: str
    anchor: str
    kind: str  # "file" | "page" | "external"  (URL-shape classification)
    link_context: str = _OTHER  # file_component | card_or_listing | inline | other
    document_type: str | None = None  # data-ema-document-type, for .bcl-file cards

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


def _text(el: Tag) -> str:
    return re.sub(r"\s+", " ", el.get_text(separator=" ", strip=True)).strip()


def _classes(el: Tag) -> set[str]:
    c = el.get("class")
    if isinstance(c, list):
        return set(c)
    return {c} if isinstance(c, str) else set()


def _attr(el: Tag, name: str) -> str | None:
    v = el.get(name)
    return v if isinstance(v, str) else None


# ── raw candidate = (href, anchor, link_context, document_type) ──────────────
_Candidate = tuple[str, str, str, "str | None"]


class _MainContentWalker:
    """Recursive, component-aware walk of ``main`` collecting link candidates.

    Mirrors ``EmaPageParser._parse_children``: descends into generic containers
    (so deeply-nested links are still found), special-cases BCL components to
    assign ``link_context``, skips nav/chrome regions, and uses an ``id()``-based
    processed-set to avoid emitting the same subtree twice.
    """

    def __init__(self) -> None:
        self.candidates: list[_Candidate] = []
        self._processed: set[int] = set()

    def _should_skip(self, el: Tag) -> bool:
        if el.name in _SKIP_TAGS or el.name == "nav":
            return True
        if id(el) in self._processed:
            return True
        return bool(_classes(el) & _SKIP_CLASSES)

    def _mark(self, el: Tag) -> None:
        self._processed.add(id(el))
        for d in el.descendants:
            if isinstance(d, Tag):
                self._processed.add(id(d))

    def _emit(self, a: Tag, context: str, document_type: str | None, anchor: str | None = None) -> None:
        href = (_attr(a, "href") or "").strip()
        if not href:
            return
        self.candidates.append((href, anchor if anchor is not None else _text(a), context, document_type))

    def _emit_file(self, el: Tag) -> None:
        """A ``.bcl-file`` document card: every download link is a file_component
        link whose anchor is the card's file-title (fallback: the link text)."""
        document_type = _attr(el, "data-ema-document-type")
        title_el = el.find(class_="file-title")
        title = _text(title_el) if isinstance(title_el, Tag) else None
        for a in el.find_all("a", href=True):
            self._emit(a, _FILE_COMPONENT, document_type, anchor=title or _text(a))

    def _emit_all_inside(self, el: Tag, context: str) -> None:
        for a in el.find_all("a", href=True):
            self._emit(a, context, None)

    def walk(self, element: Tag, context: str | None = None) -> None:
        for child in element.children:
            if not isinstance(child, Tag) or self._should_skip(child):
                continue
            classes = _classes(child)

            if "bcl-file" in classes:
                self._emit_file(child)
                self._mark(child)
                continue
            if classes & _CARD_CLASSES:
                self.walk(child, _CARD_OR_LISTING)  # card title / body links -> card_or_listing
                self._mark(child)
                continue

            if context == _CARD_OR_LISTING:
                # inside a card/listing subtree every link is card_or_listing
                if child.name == "a":
                    self._emit(child, _CARD_OR_LISTING, None)
                else:
                    self.walk(child, _CARD_OR_LISTING)
                continue

            # body flow (context is None)
            if child.name in _TEXT_TAGS:
                self._emit_all_inside(child, _INLINE)  # paragraph/list/table/etc. text links
                self._mark(child)
            elif child.name == "a":
                self._emit(child, _OTHER, None)  # standalone anchor in a container
            elif child.name in _CONTAINER_TAGS:
                self.walk(child, None)  # accordion / generic wrapper -> recurse, stay inline-by-content
            else:
                self.walk(child, None)


def extract_links(
    html: str,
    base_url: str,
    *,
    allowed_domains: tuple[str, ...] = ALLOWED_DOMAINS,
) -> list[ExtractedLink]:
    """De-duplicated outgoing links from the page's ``main-content-wrapper``.

    Scoped to ``<main class="main-content-wrapper">`` (chrome outside it is
    ignored). Returns ``[]`` when that element is absent. URL normalization is
    unchanged from the pre-port extractor (``urljoin`` against ``base_url``,
    fragment stripping, ``http(s)``-only, self-reference drop, ``ema.europa.eu``
    allowed-domain → ``kind``); on a duplicate target the richest ``link_context``
    is kept (``file_component`` > ``card_or_listing`` > ``inline`` > ``other``).
    """
    soup = BeautifulSoup(html or "", "html.parser")  # parity with EmaPageParser
    main = soup.find("main", class_=MAIN_SELECTOR_CLASS)
    if not isinstance(main, Tag):
        if soup.find("a", href=True):
            _log.warning("no main-content-wrapper for %s — anchors ignored", base_url)
        return []

    walker = _MainContentWalker()
    walker.walk(main)

    base_norm = _strip_fragment(base_url)
    seen: dict[str, ExtractedLink] = {}
    for href, anchor, context, document_type in walker.candidates:
        if not href or href.startswith("#"):
            continue
        if any(href.lower().startswith(s) for s in _SKIP_SCHEMES):
            continue
        tgt = _strip_fragment(urljoin(base_url, href))
        if not urlsplit(tgt).scheme.startswith("http"):
            continue
        if tgt == base_norm:  # self-reference
            continue
        link = ExtractedLink(
            tgt_url=tgt,
            anchor=anchor[:200],
            kind=_classify(tgt, allowed_domains),
            link_context=context,
            document_type=document_type,
        )
        prev = seen.get(tgt)
        if prev is None or _CONTEXT_PRIORITY[context] > _CONTEXT_PRIORITY[prev.link_context]:
            seen[tgt] = link
    return list(seen.values())
