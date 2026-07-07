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
    """A single cited source passage.

    The LLM only ever needs to fill ``source_url`` (the URL shown in the search
    results it relied on); every other field is provenance that the runner
    backfills from the retrieved nodes (see ``harness.agents.runner``).
    """

    source_url: str = Field(
        default="", description="URL of the source passage, exactly as shown in the search results."
    )
    doc_id: str = Field(default="", description="Internal document id (filled by the system).")
    chunk_id: str = Field(default="", description="Internal chunk id (filled by the system).")
    quote: str = Field(
        default="", description="Snippet of the cited passage (filled by the system)."
    )
    score: float | None = Field(
        default=None, description="Retrieval score of the cited passage (filled by the system)."
    )
    # Reference metadata, backfilled from the retrieved document node (F-attribution).
    title: str = Field(default="", description="Source document title (filled by the system).")
    topic_path: str = Field(
        default="", description="EMA site topic path of the source (filled by the system)."
    )
    committee: str = Field(
        default="", description="EMA committee (e.g. CHMP) when known (filled by the system)."
    )
    reference_number: str = Field(
        default="", description="EMA reference number (e.g. EMA/409815/2020) when known."
    )
    source_type: str = Field(default="", description="pdf | html (filled by the system).")
    category: str = Field(
        default="",
        description=(
            "Source category: scientific_guideline | qa | epar | medicine_page | other "
            "(filled by the system)."
        ),
    )


class Claim(BaseModel):
    """One assertion in the answer, with the citations that support it."""

    text: str = Field(
        description=(
            "A verbatim, contiguous quote copied EXACTLY from `answer` — the exact "
            "substring this claim's citations support. Do not paraphrase, shorten, or "
            "reword; copy the characters as they appear in `answer`."
        )
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description="The retrieved sources (by source_url) that support exactly this text span.",
    )


class RegulatoryAnswer(BaseModel):
    """Structured final answer produced by the regulatory agent."""

    answer: str = Field(description="The complete answer text shown to the user.")
    claims: list[Claim] = Field(
        default_factory=list,
        description=(
            "Every supported assertion in `answer`, each as a VERBATIM span of `answer` "
            "with the citations backing it. Together the claims should cover the "
            "substantive statements of the answer."
        ),
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description="All sources relied on (by source_url); the system rebuilds provenance.",
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Overall confidence in the answer, 0-1."
    )
    caveats: list[str] = Field(
        default_factory=list, description="Limitations, gaps, or scope notes for the answer."
    )

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

    source_url = str(meta.get("source_url") or "")
    topic_path = str(meta.get("topic_path") or "")
    category = str(meta.get("category") or "")
    if not category and (source_url or topic_path):
        # Lazy import keeps this module pydantic-only at import time.
        from harness.retrieval.doc_categories import classify_source

        category = classify_source(source_url, topic_path)

    return Citation(
        source_url=source_url,
        doc_id=str(meta.get("doc_id") or ""),
        chunk_id=str(meta.get("chunk_id") or meta.get("id") or ""),
        quote=quote,
        score=(float(score) if score is not None else None),
        title=str(meta.get("title") or ""),
        topic_path=topic_path,
        committee=str(meta.get("committee") or ""),
        reference_number=str(meta.get("reference_number") or ""),
        source_type=str(meta.get("source_type") or ""),
        category=category,
    )
