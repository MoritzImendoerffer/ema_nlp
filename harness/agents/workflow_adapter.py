"""Adapt an :class:`AgentSession` to the ``invoke``/``ainvoke`` runner contract.

The agentic ``FunctionAgent`` is the single engine; ``harness.recipes.build_recipe``
wraps a session in this adapter so ``app.py`` / scripts / eval consume the uniform
``invoke``/``ainvoke`` → ``{"answer_text", "docs", "answer"}`` contract. The structured
``RegulatoryAnswer`` is mapped to that dict; citations become lightweight doc-like objects
so the source sidebar renders cited URLs + quotes. The resolved recipe config is stamped
on the turn span (``extra_attributes``).

MLflow ``llama_index.autolog()`` (enabled in ``app.py`` via ``setup_tracing``) traces the
FunctionAgent automatically, so each turn is one MLflow trace that 👍/👎 feedback attaches
to. ``arun`` here does not open a separate recorded run; per-experiment run-recording stays
on the demo/eval entrypoints (``AgentSession.arun(record=True)``).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from harness.schemas import RegulatoryAnswer


class _CitationDoc:
    """Minimal doc-like view of a :class:`~harness.schemas.Citation` for the sidebar.

    Mirrors the ``.metadata`` (dict) + ``.text`` attributes ``app._run_pipeline`` reads
    off retrieved nodes, so agent citations render in the existing source panel.
    """

    def __init__(self, citation: Any) -> None:
        self.text = getattr(citation, "quote", "") or ""
        score = getattr(citation, "score", None)
        self.metadata = {
            "source_url": getattr(citation, "source_url", "") or "",
            # Citations are now node-derived (real retrieval score); the sidebar
            # formats ``score`` with ``:.3f`` so coerce a missing score to 0.0.
            "score": score if isinstance(score, (int, float)) else 0.0,
            "doc_id": getattr(citation, "doc_id", "") or "",
            "chunk_id": getattr(citation, "chunk_id", "") or "",
            "topic_path": "",
        }


class AgentWorkflowAdapter:
    """Expose an :class:`AgentSession` through the WorkflowRunner invoke/ainvoke contract."""

    def __init__(self, session: Any, *, extra_attributes: dict[str, Any] | None = None) -> None:
        self._session = session
        # Resolved recipe config (honest ``ema.*`` stamping) merged onto every turn span.
        self._extra_attributes = dict(extra_attributes or {})

    def _config_attributes(self, payload: dict) -> dict[str, Any]:
        """``ema.*`` attributes for the agent turn — same root-span contract as
        ``WorkflowRunner`` so agent and workflow traces share one shape."""
        attrs: dict[str, Any] = {
            "ema.orchestration.strategy": "agent",
            "ema.index.profile": os.getenv("EMA_INDEX_PROFILE", "neo4j_hier"),
        }
        attrs.update(self._extra_attributes)
        if payload.get("few_shot_context"):
            attrs["ema.fewshot.injected"] = True  # runtime fact: examples were prepended
        if run_id := payload.get("run_id"):
            attrs["ema.run.id"] = str(run_id)
        if source := payload.get("source"):
            attrs["ema.run.source"] = str(source)
        return attrs

    async def ainvoke(self, payload: dict) -> dict:
        from harness.obs.tracing import record_answer_on_span, traced
        from harness.tools.search import capture_search_nodes

        question = payload.get("question", "")
        # Optional rated-trajectory few-shot examples (recipe.fewshot): prepend to the
        # task, but record the ORIGINAL question as the span input.
        few_shot = (payload.get("few_shot_context") or "").strip()
        user_msg = f"{few_shot}\n\nNow answer this question:\n{question}" if few_shot else question
        with traced("AgentWorkflowAdapter.invoke", attributes=self._config_attributes(payload)) as span:
            # Capture the FULL retrieved passages (not just the truncated citation quotes)
            # so a downstream judge can grade faithfulness against the real context. The
            # inner capture in arun_agent reuses this sink (see capture_search_nodes).
            with capture_search_nodes() as evidence:
                answer: RegulatoryAnswer = await self._session.arun(user_msg)
            record_answer_on_span(span, question=question, answer=answer)
            context_passages = [
                t for nws in evidence
                if (t := (getattr(getattr(nws, "node", nws), "text", "") or "").strip())
            ]
            return {
                "answer_text": answer.answer,
                "docs": [_CitationDoc(c) for c in answer.citations],
                "answer": answer,
                "context_passages": context_passages,
            }

    def invoke(self, payload: dict) -> dict:
        """Synchronous entrypoint (CLI/tests; ``app.py`` uses :meth:`ainvoke`)."""
        return asyncio.run(self.ainvoke(payload))
