"""Run a configured agent and coerce its output to a ``RegulatoryAnswer``.

The agent's native structured output (``output_cls=RegulatoryAnswer``) is used
when present; otherwise the raw response text is wrapped, with citations drawn
from ``fallback_nodes`` (the retrieved evidence). The resolved retrieval config is
stamped on the current trace span before the run (transparency).

``coerce_answer`` is pure and unit-tested; ``arun_agent``/``run_agent`` are thin
async/sync drivers (the live LLM call is exercised at runtime, not in tests).
"""

import asyncio
import logging
from typing import Any

from harness.schemas import RegulatoryAnswer, citation_from_node

log = logging.getLogger(__name__)


def _extract_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    response = getattr(result, "response", None)
    if response is None:
        return str(result)
    content = getattr(response, "content", None)
    return content if isinstance(content, str) else str(response)


def coerce_answer(result: Any, *, fallback_nodes: list | None = None) -> RegulatoryAnswer:
    """Coerce an agent result into a ``RegulatoryAnswer`` (robust to output shape)."""
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

    text = _extract_text(result)
    citations = [citation_from_node(n) for n in (fallback_nodes or [])]
    return RegulatoryAnswer(answer=text or "No answer generated.", citations=citations)


async def arun_agent(
    agent: Any,
    query: str,
    *,
    pipeline_config: Any = None,
    fallback_nodes: list | None = None,
) -> RegulatoryAnswer:
    """Run ``agent`` on ``query`` and return a structured ``RegulatoryAnswer``."""
    if pipeline_config is not None:
        from harness.obs import stamp_current_span

        stamp_current_span(pipeline_config.resolved_attributes())

    result = await agent.run(user_msg=query)
    return coerce_answer(result, fallback_nodes=fallback_nodes)


def run_agent(
    agent: Any,
    query: str,
    *,
    pipeline_config: Any = None,
    fallback_nodes: list | None = None,
) -> RegulatoryAnswer:
    """Synchronous wrapper around :func:`arun_agent` (for scripts/tests)."""
    return asyncio.run(
        arun_agent(agent, query, pipeline_config=pipeline_config, fallback_nodes=fallback_nodes)
    )
