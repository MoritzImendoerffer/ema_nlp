"""Unit tests for harness.attribution (claim-span matching + reference numbering)."""

from harness.attribution import Attribution, build_attribution, match_spans
from harness.schemas import Citation, Claim, RegulatoryAnswer

ANSWER = (
    "The Acceptable Intake for NDMA is 96 ng/day. "
    "MAHs must inform the Agency at least 2 months in advance."
)

C1 = Citation(source_url="https://ema.eu/nitrosamines", chunk_id="c1", quote="the AI of NDMA is 96 ng/day", score=0.9)
C2 = Citation(source_url="https://ema.eu/variations", chunk_id="c2", quote="inform the Agency 2 months in advance", score=0.8)


def _answer(claims):
    return RegulatoryAnswer(answer=ANSWER, claims=claims, citations=[C1, C2], confidence=0.8)


# ── span matching ─────────────────────────────────────────────────────────────

def test_exact_verbatim_claim_matches():
    [m] = match_spans(ANSWER, ["The Acceptable Intake for NDMA is 96 ng/day."])
    assert m is not None
    start, end, idx = m
    assert ANSWER[start:end] == "The Acceptable Intake for NDMA is 96 ng/day."
    assert idx == 0


def test_whitespace_and_case_drift_still_exact():
    [m] = match_spans(ANSWER, ["the  acceptable   intake FOR NDMA is 96 ng/day."])
    assert m is not None
    assert ANSWER[m[0] : m[1]] == "The Acceptable Intake for NDMA is 96 ng/day."


def test_fuzzy_matches_light_paraphrase():
    # Missing leading "The" + trailing period — the historical claim style.
    [m] = match_spans(ANSWER, ["Acceptable Intake for NDMA is 96 ng/day"])
    assert m is not None
    assert "96 ng/day" in ANSWER[m[0] : m[1]]


def test_unrelated_claim_returns_none():
    [m] = match_spans(ANSWER, ["Bananas are an excellent source of potassium in the diet."])
    assert m is None


def test_tiny_claim_skipped():
    [m] = match_spans(ANSWER, ["NDMA"])
    assert m is None  # too short to anchor unambiguously


# ── build_attribution ─────────────────────────────────────────────────────────

def test_attribution_numbers_references_by_first_use():
    answer = _answer(
        [
            # Second sentence claimed first in the list, but appears LATER in text →
            # its reference must still be numbered by text order.
            Claim(text="MAHs must inform the Agency at least 2 months in advance.", citations=[C2]),
            Claim(text="The Acceptable Intake for NDMA is 96 ng/day.", citations=[C1]),
        ]
    )
    att = build_attribution(answer, ["full passage about NDMA", "full passage about variations"])
    assert [s.ref_ns for s in att.spans] == [[1], [2]]
    assert att.references[0].n == 1 and att.references[0].citation.chunk_id == "c1"
    assert att.references[1].n == 2 and att.references[1].citation.chunk_id == "c2"


def test_marked_text_injects_markers_after_spans():
    answer = _answer([Claim(text="The Acceptable Intake for NDMA is 96 ng/day.", citations=[C1])])
    att = build_attribution(answer)
    assert "96 ng/day. [1]" in att.marked_text
    assert att.marked_text.startswith("The Acceptable Intake")


def test_zero_claims_degrades_to_plain_answer():
    answer = _answer([])
    att = build_attribution(answer)
    assert att.marked_text == ANSWER
    assert att.spans == []
    # References still numbered (citation order) so cards/export stay usable.
    assert [r.n for r in att.references] == [1, 2]


def test_unmatched_claim_reported_not_marked():
    answer = _answer([Claim(text="Something entirely absent from the answer text here.", citations=[C1])])
    att = build_attribution(answer)
    assert att.spans == []
    assert len(att.unmatched_claims) == 1
    assert att.marked_text == ANSWER


def test_claim_citations_resolve_by_url_when_no_chunk_id():
    url_only = Citation(source_url="https://ema.eu/nitrosamines")  # the LLM-emitted style
    answer = _answer([Claim(text="The Acceptable Intake for NDMA is 96 ng/day.", citations=[url_only])])
    att = build_attribution(answer)
    assert att.spans and att.spans[0].ref_ns == [1]
    assert att.references[0].citation.chunk_id == "c1"  # resolved to the enriched citation


def test_quote_located_inside_full_passage():
    full = "Background text. According to CHMP, the AI of NDMA is 96 ng/day. More text."
    answer = _answer([])
    att = build_attribution(answer, [full, ""])
    ref1 = att.references[0]
    assert ref1.full_text == full
    assert full[ref1.quote_start : ref1.quote_end] == "the AI of NDMA is 96 ng/day"
    ref2 = att.references[1]
    assert ref2.full_text == C2.quote  # empty full text falls back to the quote


def test_overlapping_claims_longer_wins_identical_merge():
    long_claim = Claim(text="The Acceptable Intake for NDMA is 96 ng/day.", citations=[C1])
    sub_claim = Claim(text="Intake for NDMA is 96 ng/day", citations=[C2])
    dup_claim = Claim(text="The Acceptable Intake for NDMA is 96 ng/day.", citations=[C2])
    att = build_attribution(_answer([long_claim, sub_claim, dup_claim]))
    assert len(att.spans) == 1  # sub-span dropped, duplicate merged
    assert att.spans[0].ref_ns == [1, 2]


def test_to_dict_is_json_safe_and_complete():
    import json

    answer = _answer([Claim(text="The Acceptable Intake for NDMA is 96 ng/day.", citations=[C1])])
    d = build_attribution(answer, ["full ndma passage", "full var passage"]).to_dict()
    json.dumps(d)  # must not raise
    assert d["answer_text"] == ANSWER
    assert "[1]" in d["marked_text"]
    assert d["spans"][0]["refs"] == [1]
    assert d["references"][0]["source_url"] == C1.source_url
    assert d["references"][0]["full_text"] == "full ndma passage"


def test_attribution_marked_text_no_spans_property():
    att = Attribution(answer_text="plain")
    assert att.marked_text == "plain"
