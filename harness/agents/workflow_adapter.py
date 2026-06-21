"""Adapt an :class:`AgentSession` to the WorkflowRunner ``invoke``/``ainvoke`` contract.

This lets the agentic ``FunctionAgent`` be selected as a workflow *strategy* in
``app.py``'s registry-driven panel — **additive**: the existing workflows and the live
Phoenix wiring are untouched, and the agent simply registers as one more builder
(``harness.workflows.registry``). The agent's structured ``RegulatoryAnswer`` is mapped
to the ``{"answer_text", "docs"}`` dict the Chainlit pipeline expects; citations become
lightweight doc-like objects so the source sidebar renders cited URLs + quotes.

Phoenix (registered with ``auto_instrument`` in ``app.py``) traces the FunctionAgent
automatically, so no MLflow is introduced into the live path. Run-recording stays on the
demo/eval entrypoints (``AgentSession.arun(record=True)``).
"""

from __future__ import annotations

import asyncio
from typing import Any

from harness.schemas import RegulatoryAnswer


class _CitationDoc:
    """Minimal doc-like view of a :class:`~harness.schemas.Citation` for the sidebar.

    Mirrors the ``.metadata`` (dict) + ``.text`` attributes ``app._run_pipeline`` reads
    off retrieved nodes, so agent citations render in the existing source panel.
    """

    def __init__(self, citation: Any) -> None:
        self.text = getattr(citation, "quote", "") or ""
        self.metadata = {
            "source_url": getattr(citation, "source_url", "") or "",
            "score": 0.0,
            "topic_path": "",
        }


class AgentWorkflowAdapter:
    """Expose an :class:`AgentSession` through the WorkflowRunner invoke/ainvoke contract."""

    def __init__(self, session: Any) -> None:
        self._session = session

    async def ainvoke(self, payload: dict) -> dict:
        answer: RegulatoryAnswer = await self._session.arun(payload.get("question", ""))
        return {
            "answer_text": answer.answer,
            "docs": [_CitationDoc(c) for c in answer.citations],
            "answer": answer,
        }

    def invoke(self, payload: dict) -> dict:
        """Synchronous entrypoint (CLI/tests; ``app.py`` uses :meth:`ainvoke`)."""
        return asyncio.run(self.ainvoke(payload))


def build_agent_workflow(
    retriever: Any, llm: Any, *, agent_name: str = "regulatory", **_: Any
) -> AgentWorkflowAdapter:
    """Build the agent as a workflow-compatible runner over an existing retriever + llm.

    Uses a plain retrieve (``pipeline_config=None`` → no extra cross-encoder rerank) to
    stay GPU-light in the live app — the hierarchical retriever already does
    small-to-big + links. The full config-driven pipeline (query expansion + rerank) is
    available via :func:`harness.agents.session.build_session` for the demo + eval paths.
    Extra kwargs (e.g. ``prompt_strategy`` forwarded by ``get_workflow``) are ignored.
    """
    from harness.agents.session import AgentSession, assemble_agent

    agent = assemble_agent(
        base_retriever=retriever, llm=llm, agent_name=agent_name, pipeline_config=None
    )
    return AgentWorkflowAdapter(AgentSession(agent=agent))
