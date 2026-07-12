"""Page-badge extractor — EMA's curated ``(audience, site_topic)`` page labels.

EMA pages carry self-describing header badges inside ``main-content-wrapper``
(verified against the scraped ``web_items`` snapshot, 2026-07-12: ~93% of HTML
pages have an ``ema-bg-category`` badge, 90% exactly one):

    <span class="ema-bg-category ..."><span class="label">Human</span></span>
    <span class="ema-bg-topic ..."><span class="label">Scientific guidelines</span></span>

``ema-bg-category`` is the audience (Human / Veterinary / Corporate / Herbal) —
an authoritative version of what the URL-substring rules in
``harness.retrieval.doc_categories`` only approximate. ``ema-bg-topic`` is a
curated subject taxonomy (Pharmacovigilance, Clinical trials, ...) that is NOT
derivable from the URL — present on ~55% of pages.

We take the FIRST badge of each class inside ``main`` (the page's own header
badge; listing cards further down also carry badges, but on pages that have
both, the header badge comes first). Known limitation: a listing page with no
header badge of its own would pick up its first card's badge — acceptable for
metadata that is advisory, and consistent with how ``links.py`` treats cards.

Badges appear only on HTML pages; PDFs get no badge here. (Propagating labels
to PDFs over ``LINKS_TO`` edges, or joining EMA's website-data JSON export, is
a separate, deferred step.)
"""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from harness.indexing.links import MAIN_SELECTOR_CLASS

_AUDIENCE_CLASS = "ema-bg-category"
_TOPIC_CLASS = "ema-bg-topic"


@dataclass(frozen=True)
class PageBadges:
    audience: str | None = None  # Human | Veterinary | Corporate | Herbal
    site_topic: str | None = None  # EMA's curated topic label


def _first_badge_label(root: Tag, badge_class: str) -> str | None:
    badge = root.find("span", class_=badge_class)
    if not isinstance(badge, Tag):
        return None
    label = badge.find("span", class_="label")
    text = (label if isinstance(label, Tag) else badge).get_text(strip=True)
    return text or None


def extract_badges(html: str) -> PageBadges:
    """The page's own ``(audience, site_topic)`` header badges, if any.

    Scoped to ``<main class="main-content-wrapper">`` like the link extractor;
    returns empty badges when the element (or the badges) are absent.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    main = soup.find("main", class_=MAIN_SELECTOR_CLASS)
    if not isinstance(main, Tag):
        return PageBadges()
    return PageBadges(
        audience=_first_badge_label(main, _AUDIENCE_CLASS),
        site_topic=_first_badge_label(main, _TOPIC_CLASS),
    )
