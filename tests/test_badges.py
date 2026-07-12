"""Unit tests for harness.indexing.badges (EMA page-badge extractor)."""

from harness.indexing.badges import PageBadges, extract_badges

# The live EMA markup shape (2026-07): header badge pair inside main.
_BADGE_PAIR = (
    '<div class="card-badge-wrapper d-flex flex-row flex-wrap gap-3 align-items-start">'
    '<span class="ema-bg-category badge rounded-pill badge-outline-primary">'
    '<span class="label">Human</span></span>'
    '<span class="ema-bg-topic badge rounded-pill badge-outline-primary">'
    '<span class="label">Regulatory and procedural guidance</span></span></div>'
)


def _page(body: str) -> str:
    return f'<html><body><main class="main-content-wrapper">{body}</main></body></html>'


def test_extracts_audience_and_topic_from_live_markup():
    assert extract_badges(_page(_BADGE_PAIR)) == PageBadges(
        audience="Human", site_topic="Regulatory and procedural guidance"
    )


def test_audience_only_page():
    html = _page(
        '<span class="ema-bg-category badge"><span class="label">Corporate</span></span>'
    )
    assert extract_badges(html) == PageBadges(audience="Corporate", site_topic=None)


def test_first_badge_wins_over_listing_cards():
    # header badge first, then a listing card with a different badge pair
    card = _BADGE_PAIR.replace("Human", "Veterinary").replace(
        "Regulatory and procedural guidance", "Medicines"
    )
    html = _page(_BADGE_PAIR + '<div class="bcl-listing">' + card + "</div>")
    assert extract_badges(html) == PageBadges(
        audience="Human", site_topic="Regulatory and procedural guidance"
    )


def test_badge_outside_main_is_ignored():
    html = (
        "<html><body>"
        f"<header>{_BADGE_PAIR}</header>"
        '<main class="main-content-wrapper"><p>no badges here</p></main>'
        "</body></html>"
    )
    assert extract_badges(html) == PageBadges()


def test_no_main_content_wrapper_returns_empty():
    assert extract_badges(f"<html><body>{_BADGE_PAIR}</body></html>") == PageBadges()
    assert extract_badges("") == PageBadges()


def test_label_span_missing_falls_back_to_badge_text():
    html = _page('<span class="ema-bg-category badge">Herbal</span>')
    assert extract_badges(html).audience == "Herbal"
