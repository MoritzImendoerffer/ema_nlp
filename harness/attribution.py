"""Answer↔citation attribution: locate claim spans and number references.

The single source of attribution truth for the chat UI, the HTML/Markdown
exports, and the SME review element. Claims are prompted to be *verbatim* spans
of the answer (see ``harness/prompts/agent_*.md`` + the ``Claim.text`` field
description); this module locates them robustly anyway:

  1. exact match on normalized text (casefold + whitespace-collapse, with an
     offset map back to the original string), then
  2. a ``difflib.SequenceMatcher`` sliding-window fallback (paraphrase drift),

and degrades gracefully — unmatched claims are reported, zero claims yields an
attribution with no spans (the pre-attribution behavior).

Reference numbering is by first appearance in the answer text; citations never
anchored to a span keep their (score-sorted) order after the anchored ones.
Everything here is pure and offline-tested.
"""

from __future__ import annotations

import difflib
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from harness.schemas import Citation, RegulatoryAnswer

log = logging.getLogger(__name__)

FUZZY_THRESHOLD = 0.85
_MIN_CLAIM_CHARS = 8  # normalized; shorter claims are too ambiguous to anchor


# ── normalization with an offset map ─────────────────────────────────────────

def _normalize(text: str) -> tuple[str, list[int]]:
    """Casefolded, whitespace-collapsed copy of ``text`` + per-char source offsets.

    ``offsets[i]`` is the index in the ORIGINAL string of the character that
    produced normalized char ``i`` — so normalized match positions map back to
    original-string spans.
    """
    chars: list[str] = []
    offsets: list[int] = []
    pending_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            pending_space = bool(chars)  # collapse runs; strip leading
            continue
        if pending_space:
            chars.append(" ")
            offsets.append(i - 1)
            pending_space = False
        for low in ch.casefold():  # rare 1->n casefolds keep the map aligned
            chars.append(low)
            offsets.append(i)
    return "".join(chars), offsets


# ── data model ────────────────────────────────────────────────────────────────

@dataclass
class Span:
    """A region of the answer text attributable to one or more references."""

    start: int
    end: int  # exclusive, original-string coordinates
    ref_ns: list[int] = field(default_factory=list)  # 1-based reference numbers


@dataclass
class Reference:
    """One numbered reference: the citation plus its full source passage."""

    n: int
    citation: Citation
    full_text: str = ""
    quote_start: int = -1  # citation.quote located inside full_text (-1 = not found)
    quote_end: int = -1

    def to_dict(self) -> dict[str, Any]:
        d = self.citation.model_dump()
        d.update(
            n=self.n,
            full_text=self.full_text,
            quote_start=self.quote_start,
            quote_end=self.quote_end,
        )
        return d


@dataclass
class Attribution:
    """The resolved answer↔reference attribution for one turn."""

    answer_text: str
    spans: list[Span] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    unmatched_claims: list[str] = field(default_factory=list)

    @property
    def marked_text(self) -> str:
        """Answer text with ``[n]`` markers injected after each attributed span."""
        if not self.spans:
            return self.answer_text
        out = self.answer_text
        for span in sorted(self.spans, key=lambda s: s.end, reverse=True):
            if not span.ref_ns:
                continue
            markers = "".join(f"[{n}]" for n in sorted(set(span.ref_ns)))
            sep = "" if (span.end < len(out) and out[span.end - 1].isspace()) else " "
            out = out[: span.end] + sep + markers + out[span.end :]
        return out

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe dict shared by the SME review element and the HTML export."""
        return {
            "answer_text": self.answer_text,
            "marked_text": self.marked_text,
            "spans": [
                {"start": s.start, "end": s.end, "refs": sorted(set(s.ref_ns))}
                for s in self.spans
            ],
            "references": [r.to_dict() for r in self.references],
            "unmatched_claims": list(self.unmatched_claims),
        }


# ── span matching ─────────────────────────────────────────────────────────────

def _find_exact(answer_norm: str, offsets: list[int], claim_norm: str, answer_len: int) -> tuple[int, int] | None:
    j = answer_norm.find(claim_norm)
    if j < 0:
        return None
    start = offsets[j]
    last = j + len(claim_norm) - 1
    end = offsets[last] + 1
    return (start, min(end, answer_len))


def _find_fuzzy(answer_norm: str, offsets: list[int], claim_norm: str, answer_len: int) -> tuple[int, int] | None:
    w = len(claim_norm)
    if len(answer_norm) <= w:
        ratio = difflib.SequenceMatcher(None, claim_norm, answer_norm).ratio()
        if ratio >= FUZZY_THRESHOLD and answer_norm:
            return (offsets[0], answer_len)
        return None
    best_ratio, best_start = 0.0, -1
    step = max(1, w // 5)
    matcher = difflib.SequenceMatcher(None, claim_norm, "")
    for j in range(0, len(answer_norm) - w + 1, step):
        matcher.set_seq2(answer_norm[j : j + w])
        ratio = matcher.ratio()
        if ratio > best_ratio:
            best_ratio, best_start = ratio, j
    if best_ratio < FUZZY_THRESHOLD or best_start < 0:
        return None
    last = best_start + w - 1
    return (offsets[best_start], min(offsets[last] + 1, answer_len))


def match_spans(answer: str, claim_texts: Sequence[str]) -> list[tuple[int, int, int] | None]:
    """Locate each claim in ``answer``; item i is ``(start, end, claim_index)`` or None.

    Exact normalized match first, fuzzy fallback second. No overlap resolution
    here — see :func:`build_attribution`.
    """
    answer_norm, offsets = _normalize(answer)
    results: list[tuple[int, int, int] | None] = []
    for idx, claim_text in enumerate(claim_texts):
        claim_norm, _ = _normalize(claim_text or "")
        if len(claim_norm) < _MIN_CLAIM_CHARS:
            results.append(None)
            continue
        found = _find_exact(answer_norm, offsets, claim_norm, len(answer)) or _find_fuzzy(
            answer_norm, offsets, claim_norm, len(answer)
        )
        results.append((found[0], found[1], idx) if found else None)
    return results


def _resolve_overlaps(matches: list[tuple[int, int, int]]) -> list[tuple[int, int, list[int]]]:
    """Non-overlapping spans, longer-then-earlier wins; identical ranges merge."""
    accepted: list[tuple[int, int, list[int]]] = []
    for start, end, claim_idx in sorted(matches, key=lambda m: (-(m[1] - m[0]), m[0])):
        merged = False
        for acc in accepted:
            if acc[0] == start and acc[1] == end:
                acc[2].append(claim_idx)
                merged = True
                break
        if merged:
            continue
        if any(start < a_end and end > a_start for a_start, a_end, _ in accepted):
            continue  # overlapping, shorter/later — dropped
        accepted.append((start, end, [claim_idx]))
    return sorted(accepted, key=lambda a: a[0])


# ── reference resolution + numbering ─────────────────────────────────────────

def _ref_key(citation: Citation) -> str:
    return citation.chunk_id or citation.source_url or citation.quote


def _locate_quote(quote: str, full_text: str) -> tuple[int, int]:
    quote = quote.rstrip("…").strip()
    if not quote or not full_text:
        return (-1, -1)
    full_norm, offsets = _normalize(full_text)
    quote_norm, _ = _normalize(quote)
    j = full_norm.find(quote_norm)
    if j < 0 or not quote_norm:
        return (-1, -1)
    last = j + len(quote_norm) - 1
    return (offsets[j], min(offsets[last] + 1, len(full_text)))


def build_attribution(
    answer: RegulatoryAnswer, citation_texts: Sequence[str] | None = None
) -> Attribution:
    """Resolve claims → answer spans and number the references by first use.

    ``citation_texts[i]`` is the full source passage for ``answer.citations[i]``
    (falls back to the citation's truncated ``quote`` when absent/empty).
    """
    citations = list(answer.citations)
    texts = list(citation_texts or [])
    full_texts = [
        (texts[i] if i < len(texts) and texts[i] else citations[i].quote)
        for i in range(len(citations))
    ]

    # Claim -> citation indices (chunk_id join first, else source_url join).
    index_by_key: dict[str, int] = {}
    for i, cit in enumerate(citations):
        index_by_key.setdefault(_ref_key(cit), i)
        if cit.source_url:
            index_by_key.setdefault(cit.source_url, i)

    claim_refs: list[list[int]] = []
    for claim in answer.claims:
        refs: list[int] = []
        for cit in claim.citations:
            hit = index_by_key.get(_ref_key(cit))
            if hit is None and cit.source_url:
                hit = index_by_key.get(cit.source_url)
            if hit is not None and hit not in refs:
                refs.append(hit)
        claim_refs.append(refs)

    matches = match_spans(answer.answer, [c.text for c in answer.claims])
    unmatched = [
        answer.claims[i].text for i, m in enumerate(matches) if m is None and answer.claims
    ]
    resolved = _resolve_overlaps([m for m in matches if m is not None])

    # Number references by first appearance in the text; leftovers keep order.
    number_of: dict[int, int] = {}  # citation index -> reference number
    spans: list[Span] = []
    for start, end, claim_idxs in resolved:
        ref_ns: list[int] = []
        for claim_idx in claim_idxs:
            for cit_idx in claim_refs[claim_idx]:
                if cit_idx not in number_of:
                    number_of[cit_idx] = len(number_of) + 1
                ref_ns.append(number_of[cit_idx])
        if ref_ns:
            spans.append(Span(start=start, end=end, ref_ns=sorted(set(ref_ns))))
    for i in range(len(citations)):
        if i not in number_of:
            number_of[i] = len(number_of) + 1

    references = sorted(
        (
            Reference(
                n=number_of[i],
                citation=citations[i],
                full_text=full_texts[i],
                quote_start=(loc := _locate_quote(citations[i].quote, full_texts[i]))[0],
                quote_end=loc[1],
            )
            for i in range(len(citations))
        ),
        key=lambda r: r.n,
    )
    return Attribution(
        answer_text=answer.answer,
        spans=spans,
        references=references,
        unmatched_claims=unmatched,
    )
