"""Unit tests for corpus/ingestion/link_extractor.py (NARR-012)."""

from __future__ import annotations

from corpus.ingestion.link_extractor import (
    Link,
    extract_all,
    extract_from_html,
    extract_from_markdown,
    extract_reference_numbers,
    extract_see_qa,
)

# ---------------------------------------------------------------------------
# extract_from_markdown
# ---------------------------------------------------------------------------


def test_md_extracts_http_link():
    md = "See [the guideline](https://www.ema.europa.eu/en/x.pdf) for details."
    links = extract_from_markdown(md)
    assert links == [
        Link(tgt_url="https://www.ema.europa.eu/en/x.pdf", link_type="hyperlink", anchor="the guideline")
    ]


def test_md_strips_fragment():
    md = "Check [section 2](https://example.org/doc#sec-2)."
    links = extract_from_markdown(md)
    assert links[0].tgt_url == "https://example.org/doc"
    assert links[0].anchor == "section 2"


def test_md_skips_non_http():
    md = "Email [us](mailto:a@b.c) or browse [other](javascript:void(0))."
    assert extract_from_markdown(md) == []


def test_md_empty_input_returns_empty_list():
    assert extract_from_markdown("") == []
    assert extract_from_markdown(None) == []  # type: ignore[arg-type]


def test_md_handles_multiple_links_same_text():
    md = "A [x](https://a.example) and B [y](https://b.example)."
    out = extract_from_markdown(md)
    assert len(out) == 2
    assert {lnk.tgt_url for lnk in out} == {"https://a.example", "https://b.example"}


# ---------------------------------------------------------------------------
# extract_from_html
# ---------------------------------------------------------------------------


def test_html_resolves_relative_url():
    html = '<a href="/en/medicines/medicine-a">Medicine A</a>'
    links = extract_from_html(html, base_url="https://www.ema.europa.eu/en/page")
    assert links == [
        Link(
            tgt_url="https://www.ema.europa.eu/en/medicines/medicine-a",
            link_type="hyperlink",
            anchor="Medicine A",
        )
    ]


def test_html_keeps_absolute_url():
    html = '<a href="https://external.example/x">ext</a>'
    links = extract_from_html(html, base_url="https://www.ema.europa.eu/en/page")
    assert links[0].tgt_url == "https://external.example/x"


def test_html_drops_fragment_only_and_non_http():
    html = (
        '<a href="#top">top</a>'
        '<a href="mailto:foo@bar.com">foo</a>'
        '<a href="javascript:alert(1)">js</a>'
        '<a href="tel:+123">call</a>'
    )
    assert extract_from_html(html, base_url="https://www.ema.europa.eu/en/page") == []


def test_html_strips_self_reference():
    html = '<a href="https://www.ema.europa.eu/en/page">self</a><a href="other">o</a>'
    links = extract_from_html(html, base_url="https://www.ema.europa.eu/en/page")
    assert len(links) == 1
    assert links[0].tgt_url == "https://www.ema.europa.eu/en/other"


def test_html_strips_nested_markup_for_anchor():
    html = '<a href="/x"><span>Heading</span> <em>here</em></a>'
    [link] = extract_from_html(html, base_url="https://e.example/p")
    assert link.anchor == "Heading here"


def test_html_empty_returns_empty():
    assert extract_from_html("", "https://e.example/") == []
    assert extract_from_html(None, "https://e.example/") == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# extract_reference_numbers
# ---------------------------------------------------------------------------


def test_refnums_finds_multiple_codes():
    text = "Per EMA/INS/GCP/13279/2017 and also EMA/CHMP/123456/2020 …"
    links = extract_reference_numbers(text)
    assert {lnk.tgt_url for lnk in links} == {"EMA/INS/GCP/13279/2017", "EMA/CHMP/123456/2020"}
    assert all(lnk.link_type == "reference_number" for lnk in links)


def test_refnums_dedupes_same_code():
    text = "EMA/CHMP/99/2024 mentioned twice: EMA/CHMP/99/2024 again."
    links = extract_reference_numbers(text)
    assert len(links) == 1


def test_refnums_no_match_in_plain_text():
    assert extract_reference_numbers("no codes here") == []


def test_refnums_ignores_non_ema_prefix():
    assert extract_reference_numbers("FDA/12/2024 and FOO/CHMP/9/2024") == []


# ---------------------------------------------------------------------------
# extract_see_qa
# ---------------------------------------------------------------------------


def test_see_qa_finds_q_and_a():
    text = "Refer to see Q&A 5 for more details. Also see question 12."
    links = extract_see_qa(text)
    assert len(links) == 2
    assert {lnk.tgt_url for lnk in links} == {"qa:5", "qa:12"}
    assert all(lnk.link_type == "see_qa" for lnk in links)


def test_see_qa_case_insensitive():
    text = "Please SEE Q&A 7."
    assert extract_see_qa(text)[0].tgt_url == "qa:7"


def test_see_qa_no_match():
    assert extract_see_qa("nothing to see here") == []
    assert extract_see_qa("") == []


# ---------------------------------------------------------------------------
# extract_all
# ---------------------------------------------------------------------------


def test_extract_all_runs_every_extractor():
    md = (
        "See [the guideline](https://www.ema.europa.eu/en/g.pdf) and "
        "EMA/CHMP/100/2024 — also see Q&A 3."
    )
    html = '<a href="/x">x</a>'
    out = extract_all(markdown=md, html=html, base_url="https://e.example/p")
    types = {lnk.link_type for lnk in out}
    assert types == {"hyperlink", "reference_number", "see_qa"}


def test_extract_all_no_html_no_html_extraction():
    out = extract_all(markdown="EMA/CHMP/100/2024")
    assert {lnk.link_type for lnk in out} == {"reference_number"}


def test_extract_all_empty_input_returns_empty():
    assert extract_all() == []
    assert extract_all(markdown="") == []
