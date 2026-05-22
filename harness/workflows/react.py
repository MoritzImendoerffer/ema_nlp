"""
ReAct agent workflow with 4 EMA retrieval tools.

Uses LlamaIndex FunctionAgent wrapped in AgentWorkflow, exposed as a
WorkflowRunner with the standard invoke/ainvoke interface.

Tools::
    ema_search(query, k)        — hybrid RRF retrieval via retrieve_with_config
    follow_cross_refs(qa_id)    — expand cross-referenced Q&A entries
    filter_by_topic(topic)      — narrow last search results by topic/URL
    get_qa_by_id(qa_id)         — fetch a specific Q&A entry by ID

Each ainvoke() creates fresh tool closures so per-invocation state
(last_docs, trajectory, cited_qa_ids) is never shared between calls.

Output::

    {
        "answer_text":    str,
        "docs":           list[Doc],
        "trajectory":     list[dict],
        "cited_qa_ids":   list[str],
        "prompt_strategy": "react",
    }

Usage::

    from harness.workflows.react import build_react_workflow
    from harness.llms import get_llm
    from harness.embed import build_index

    index  = build_index(corpus_path, index_dir)
    runner = build_react_workflow(index=index, llm=get_llm("frontier"))
    result = runner.invoke({"question": "What is the AI for NDMA?"})
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from harness.retrieve import RetrievalConfig, retrieve_with_config
from harness.workflows.utils import Doc, results_to_docs

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are an expert on European Medicines Agency (EMA) human-regulatory procedures. "
    "Use the provided tools to find information and answer the question accurately.\n\n"
    "Always call ema_search before answering. When you have sufficient information, "
    "provide a complete, well-reasoned answer.\n\n"
    "IMPORTANT: 'AI' means Acceptable Intake (ng/day), not Artificial Intelligence, "
    "in EMA Q&A documents."
)


def _format_docs_for_agent(docs: list[Doc]) -> str:
    if not docs:
        return "No results found."
    lines: list[str] = []
    for i, doc in enumerate(docs, 1):
        meta = doc.metadata
        qa_id = meta.get("qa_id", "?")
        score = meta.get("score", 0.0)
        lines.append(f"[{i}] qa_id={qa_id} score={score:.3f}")
        lines.append(doc.page_content[:400])
        lines.append("")
    return "\n".join(lines)


class _ReactRunner:
    """WorkflowRunner-compatible wrapper for the ReAct agent."""

    def __init__(
        self,
        *,
        index: Any,
        llm: Any,
        retrieval_config: RetrievalConfig,
        max_iterations: int,
    ) -> None:
        self._index = index
        self._llm = llm
        self._config = retrieval_config
        self._max_iterations = max_iterations

    async def ainvoke(self, inputs: dict) -> dict:
        from llama_index.core.agent import AgentWorkflow, FunctionAgent
        from llama_index.core.tools import FunctionTool

        question: str = inputs.get("question", "")

        # Per-invocation state — safe because each ainvoke creates new closures.
        last_docs: list[Doc] = []
        trajectory: list[dict] = []
        cited_qa_ids: list[str] = []

        index = self._index
        config = self._config

        def ema_search(query: str, k: int = 10) -> str:
            """Search the EMA Q&A corpus using hybrid retrieval. Use this first."""
            results = retrieve_with_config(config, index, query)[:k]
            docs = results_to_docs(results, index)
            last_docs.clear()
            last_docs.extend(docs)
            trajectory.append({"type": "tool_call", "tool": "ema_search", "query": query})
            return _format_docs_for_agent(docs)

        def follow_cross_refs(qa_id: str) -> str:
            """Follow cross-references from a Q&A entry to related entries."""
            from harness.embed import follow_cross_refs as _follow
            nodes = _follow(index, qa_id)
            docs = [
                Doc(page_content=n.text, metadata=dict(n.metadata))
                for n in nodes
            ]
            last_docs.clear()
            last_docs.extend(docs)
            trajectory.append({"type": "tool_call", "tool": "follow_cross_refs", "qa_id": qa_id})
            return _format_docs_for_agent(docs) if docs else f"No cross-refs for {qa_id!r}"

        def filter_by_topic(topic: str) -> str:
            """Filter last search results by topic path or source URL substring."""
            topic_lower = topic.lower()
            filtered = [
                d for d in last_docs
                if topic_lower in (d.metadata.get("topic_path") or "").lower()
                or topic_lower in (d.metadata.get("source_url") or "").lower()
            ]
            last_docs.clear()
            last_docs.extend(filtered)
            trajectory.append({"type": "tool_call", "tool": "filter_by_topic", "topic": topic})
            return _format_docs_for_agent(filtered) if filtered else f"No results after filtering by {topic!r}"

        def get_qa_by_id(qa_id: str) -> str:
            """Fetch a specific Q&A entry by its qa_id."""
            from harness.embed import get_node_by_id
            node = get_node_by_id(index, qa_id)
            cited_qa_ids.append(qa_id)
            trajectory.append({"type": "tool_call", "tool": "get_qa_by_id", "qa_id": qa_id})
            return node.text if node else f"No entry found for qa_id={qa_id!r}"

        tools = [
            FunctionTool.from_defaults(fn=ema_search, name="ema_search"),
            FunctionTool.from_defaults(fn=follow_cross_refs, name="follow_cross_refs"),
            FunctionTool.from_defaults(fn=filter_by_topic, name="filter_by_topic"),
            FunctionTool.from_defaults(fn=get_qa_by_id, name="get_qa_by_id"),
        ]

        agent = FunctionAgent(
            tools=tools,
            llm=self._llm,
            system_prompt=_SYSTEM_PROMPT,
            max_iterations=self._max_iterations,
            verbose=False,
        )
        wf = AgentWorkflow(agents=[agent])
        handler = wf.run(user_msg=question)
        output = await handler
        answer_text = str(output).strip() or "No answer generated."

        return {
            "answer_text": answer_text,
            "docs": list(last_docs),
            "trajectory": trajectory,
            "cited_qa_ids": list(cited_qa_ids),
            "prompt_strategy": "react",
        }

    def invoke(self, inputs: dict) -> dict:
        """Synchronous invocation — safe to call outside an async context."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.ainvoke(inputs))
        finally:
            loop.close()

    def __call__(self, inputs: dict) -> dict:
        return self.invoke(inputs)


def build_react_workflow(
    *,
    index: Any,
    llm: Any,
    retrieval_config: RetrievalConfig | None = None,
    max_iterations: int = 10,
) -> _ReactRunner:
    """
    Build and return a ReAct agent runner.

    Args:
        index:            LlamaIndex VectorStoreIndex.
        llm:              LlamaIndex LLM (must support tool calling).
        retrieval_config: RetrievalConfig (defaults to flat hybrid k=10).
        max_iterations:   Max ReAct loop iterations.

    Returns:
        _ReactRunner with invoke/ainvoke interface compatible with WorkflowRunner.
    """
    return _ReactRunner(
        index=index,
        llm=llm,
        retrieval_config=retrieval_config or RetrievalConfig(),
        max_iterations=max_iterations,
    )
