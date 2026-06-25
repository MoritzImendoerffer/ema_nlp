"""Run a configured agent and coerce its output to a ``RegulatoryAnswer``.

The agent's native structured output (``output_cls=RegulatoryAnswer``) carries the
answer text, claims, confidence and caveats; otherwise the raw response text is
wrapped. Either way, the answer's **citations are rebuilt from the nodes
``ema_search`` actually retrieved during the run** (``evidence_nodes``, captured via
:func:`harness.tools.search.capture_search_nodes`) so provenance carries real
``doc_id``/``chunk_id``/``quote``/``score`` — the LLM only ever sees source URLs in
the tool output, so its self-authored citations are URL-only. The resolved
retrieval config is stamped on the current trace span before the run (transparency).

``coerce_answer`` is pure and unit-tested; ``arun_agent``/``run_agent`` are thin
async/sync drivers (the live LLM call is exercised at runtime, not in tests).
"""

import asyncio
import logging
from typing import Any

from harness.schemas import Citation, RegulatoryAnswer, citations_from_nodes

log = logging.getLogger(__name__)


def _extract_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    response = getattr(result, "response", None)
    if response is None:
        return str(result)
    content = getattr(response, "content", None)
    return content if isinstance(content, str) else str(response)


def _to_answer(result: Any) -> RegulatoryAnswer:
    """Extract a ``RegulatoryAnswer`` from an agent result (structured or text)."""
    if isinstance(result, RegulatoryAnswer):
        return result

    structured = getattr(result, "structured_response", None)
    if isinstance(structured, RegulatoryAnswer):
        return structured
    if isinstance(structured, dict):
        try:
            return RegulatoryAnswer.model_validate(structured)
        except Exception as exc:  # malformed structured output -> fall back to text
            log.warning("structured_response did not validate as RegulatoryAnswer: %s", exc)

    return RegulatoryAnswer(answer=_extract_text(result) or "No answer generated.")


def _enrich_claim_citations(answer: RegulatoryAnswer, by_url: dict[str, Citation]) -> None:
    """Backfill claim-level citations' ids/quote/score by matching ``source_url`` to nodes.

    Non-destructive: a claim citation is replaced only when it lacks a ``doc_id``
    (i.e. the URL-only one the LLM emitted) and the URL matches a retrieved node.
    """
    for claim in answer.claims:
        claim.citations = [
            (by_url.get(c.source_url) or c) if not c.doc_id else c for c in claim.citations
        ]


def coerce_answer(result: Any, *, evidence_nodes: list | None = None) -> RegulatoryAnswer:
    """Coerce an agent result into a ``RegulatoryAnswer`` with node-derived citations.

    Keeps the agent's structured answer/claims/confidence/caveats but rebuilds the
    top-level ``citations`` from ``evidence_nodes`` (the passages ``ema_search``
    retrieved) and enriches claim-level citations by URL match. When no nodes were
    captured the answer is returned unchanged (the passthrough identity is preserved
    for an already-``RegulatoryAnswer`` result).
    """
    answer = _to_answer(result)
    node_citations = citations_from_nodes(evidence_nodes or [])
    if node_citations:
        answer.citations = node_citations
        by_url: dict[str, Citation] = {}
        for cit in node_citations:
            by_url.setdefault(cit.source_url, cit)
        _enrich_claim_citations(answer, by_url)
    return answer


async def arun_agent(
    agent: Any,
    query: str,
    *,
    pipeline_config: Any = None,
    evidence_nodes: list | None = None,
) -> RegulatoryAnswer:
    """Run ``agent`` on ``query`` and return a structured ``RegulatoryAnswer``.

    Captures the nodes ``ema_search`` retrieves during the run and uses them as the
    answer's citation provenance. An explicit ``evidence_nodes`` (tests/eval) takes
    precedence over the captured set.
    """
    from harness.tools.search import capture_search_nodes

    if pipeline_config is not None:
        from harness.obs import stamp_current_span

        stamp_current_span(pipeline_config.resolved_attributes())

    with capture_search_nodes() as captured:
        result = await agent.run(user_msg=query)
    return coerce_answer(result, evidence_nodes=evidence_nodes or captured)


def run_agent(
    agent: Any,
    query: str,
    *,
    pipeline_config: Any = None,
    evidence_nodes: list | None = None,
) -> RegulatoryAnswer:
    """Synchronous wrapper around :func:`arun_agent` (for scripts/tests)."""
    return asyncio.run(
        arun_agent(agent, query, pipeline_config=pipeline_config, evidence_nodes=evidence_nodes)
    )
