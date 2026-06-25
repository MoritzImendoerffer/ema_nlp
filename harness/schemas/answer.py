"""Pydantic output contracts for agent answers (target architecture aims 2 & 4).

These make the answer *and its provenance* a first-class, validated structure
instead of a plain string:

  - ``Citation``  — one cited source passage (url + ids + quote + score)
  - ``Claim``     — a single assertion with the citations that support it
  - ``RegulatoryAnswer`` — the agent's structured final answer

Claim-level citations make faithfulness judging reliable: each claim can be
checked against its own sources. ``RegulatoryAnswer`` is used as the native
``output_cls`` of the LlamaIndex ``FunctionAgent`` (see ``harness.agents``).

This module depends only on ``pydantic`` — no LlamaIndex import — so it is cheap
to import and trivially unit-testable. ``citation_from_node`` is duck-typed and
accepts either a ``NodeWithScore`` or a bare ``TextNode``.
"""

import logging
from typing import Any

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

_QUOTE_MAX = 240


class Citation(BaseModel):
    """A single cited source passage."""

    source_url: str = ""
    doc_id: str = ""
    chunk_id: str = ""
    quote: str = ""
    score: float | None = None


class Claim(BaseModel):
    """One assertion in the answer, with the citations that support it."""

    text: str
    citations: list[Citation] = Field(default_factory=list)


class RegulatoryAnswer(BaseModel):
    """Structured final answer produced by the regulatory agent."""

    answer: str
    claims: list[Claim] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    caveats: list[str] = Field(default_factory=list)

    @classmethod
    def from_nodes(
        cls,
        answer: str,
        nodes: list[Any],
        *,
        claims: list[Claim] | None = None,
        confidence: float = 0.0,
        caveats: list[str] | None = None,
    ) -> "RegulatoryAnswer":
        """Build an answer whose top-level ``citations`` come from retrieved nodes.

        Bridges the existing retriever contract (``TextNode.metadata`` carries
        ``source_url`` / ``doc_id`` / ``score``) to the structured output.
        """
        return cls(
            answer=answer,
            citations=[citation_from_node(n) for n in nodes],
            claims=claims or [],
            confidence=confidence,
            caveats=caveats or [],
        )


def citations_from_nodes(nodes: list[Any]) -> list[Citation]:
    """Build deduped, score-sorted ``Citation`` objects from retrieved nodes.

    Dedupes by underlying node id (falling back to ``chunk_id``, then
    ``source_url|quote``), keeping the highest-scoring occurrence, and orders
    strongest-evidence-first. Used to give the agent's structured answer the same
    node-derived provenance the single-step RAG path gets from
    :meth:`RegulatoryAnswer.from_nodes` — real ``doc_id``/``chunk_id``/``quote``/``score``
    rather than the URL-only citations the LLM emits. Robust to nodes the agent
    retrieved across several ``ema_search`` calls in one run.
    """
    best: dict[str, Citation] = {}
    for node_with_score in nodes:
        cit = citation_from_node(node_with_score)
        node = getattr(node_with_score, "node", node_with_score)
        key = getattr(node, "node_id", None) or cit.chunk_id or f"{cit.source_url}|{cit.quote}"
        prev = best.get(key)
        if prev is None or (cit.score or float("-inf")) > (prev.score or float("-inf")):
            best[key] = cit
    # Stable sort keeps first-seen order among equal scores; None scores sort last.
    return sorted(
        best.values(),
        key=lambda c: c.score if c.score is not None else float("-inf"),
        reverse=True,
    )


def citation_from_node(node_with_score: Any) -> Citation:
    """Build a ``Citation`` from a ``NodeWithScore`` or bare ``TextNode``.

    Duck-typed: reads ``.node``/``.score`` when present, else treats the argument
    as the node itself and looks for ``score`` in metadata.
    """
    node = getattr(node_with_score, "node", node_with_score)
    score = getattr(node_with_score, "score", None)
    meta = dict(getattr(node, "metadata", {}) or {})
    text = getattr(node, "text", "") or ""

    quote = " ".join(text.split())
    if len(quote) > _QUOTE_MAX:
        quote = quote[:_QUOTE_MAX] + "…"

    if score is None and "score" in meta:
        try:
            score = float(meta["score"])
        except (TypeError, ValueError):
            score = None

    return Citation(
        source_url=str(meta.get("source_url", "")),
        doc_id=str(meta.get("doc_id", "")),
        chunk_id=str(meta.get("chunk_id") or meta.get("id") or ""),
        quote=quote,
        score=(float(score) if score is not None else None),
    )
