"""
LlamaIndex ReActAgent for EMA Q&A retrieval.

Four FunctionTools:
  search(query, k)           — hybrid RRF retrieval (configurable mode)
  follow_cross_refs(qa_id)   — follow metadata cross_refs, O(1) lookup
  filter_by_topic(topic)     — restrict last search results to a topic path
  answer(text, cited_qa_ids) — terminal tool, ends the agent loop

Phoenix/OpenInference instrumentation is enabled at first instantiation so
all agent traces (retrieval steps, LLM calls, latency) appear in the Phoenix UI.

Usage::

    from harness.embed import build_index
    from harness.agents.react_agent import ReActRAGAgent

    index = build_index()
    agent = ReActRAGAgent(index, model="claude-haiku-4-5-20251001")
    ans = agent.run("What is the deadline for submitting a worksharing variation?")
    print(ans.text)
    print(ans.cited_qa_ids)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from llama_index.core.agent import ReActAgent
from llama_index.core.tools import FunctionTool
from llama_index.llms.anthropic import Anthropic

from harness.embed import follow_cross_refs as _follow_cross_refs_impl
from harness.embed import get_node_by_id
from harness.retrieve import RetrievalResult, retrieve

log = logging.getLogger(__name__)

_INSTRUMENTED = False


def _ensure_instrumented() -> None:
    global _INSTRUMENTED
    if _INSTRUMENTED:
        return
    try:
        import phoenix as px
        from openinference.instrumentation.llama_index import LlamaIndexInstrumentor

        if px.active_session() is None:
            px.launch_app()
        LlamaIndexInstrumentor().instrument()
        log.info("Phoenix instrumentation active at %s", px.active_session().url if px.active_session() else "unknown")
    except Exception as exc:
        log.warning("Phoenix instrumentation unavailable: %s", exc)
    _INSTRUMENTED = True


class AgentAnswer:
    """Structured output from ReActRAGAgent.run()."""

    def __init__(self, text: str, cited_qa_ids: list[str], trajectory: list[dict]):
        self.text = text
        self.cited_qa_ids = cited_qa_ids
        self.trajectory = trajectory

    def __repr__(self) -> str:
        return f"AgentAnswer(text={self.text[:60]!r}..., cited={self.cited_qa_ids})"


class ReActRAGAgent:
    """
    LlamaIndex ReActAgent with four EMA-specific retrieval tools.

    Args:
        index:          VectorStoreIndex built by harness.embed.build_index.
        retrieval_mode: "hybrid" | "dense" | "bm25" (default: "hybrid").
        model:          Claude model ID for the ReAct LLM.
        max_steps:      Max agent iterations before forced termination.
        k:              Top-k results returned by search().
    """

    def __init__(
        self,
        index: Any,
        *,
        retrieval_mode: str = "hybrid",
        model: str = "claude-haiku-4-5-20251001",
        max_steps: int = 10,
        k: int = 10,
        fewshot_context: str | None = None,
    ) -> None:
        self.index = index
        self.retrieval_mode = retrieval_mode
        self.k = k
        self._last_results: list[RetrievalResult] = []
        self._answer_store: dict[str, Any] | None = None
        # Cache BM25 retriever to avoid rebuilding the index on every search() call
        self._bm25_retriever = None
        self._fewshot_context = fewshot_context

        _ensure_instrumented()

        tools = [
            FunctionTool.from_defaults(
                fn=self._search,
                name="search",
                description=(
                    "Search the EMA Q&A corpus for documents relevant to the query. "
                    "Returns up to k Q&A pairs with their qa_ids, scores, and source titles. "
                    "Args: query (str) — natural-language search query; "
                    "k (int, optional) — number of results to return (default 10)."
                ),
            ),
            FunctionTool.from_defaults(
                fn=self._follow_cross_refs,
                name="follow_cross_refs",
                description=(
                    "Follow the explicit cross-references embedded in a Q&A record. "
                    "Returns all Q&As that the given qa_id directly links to. "
                    "Use after search() to expand coverage for multi-hop questions "
                    "without issuing a new retrieval query. "
                    "Args: qa_id (str) — the qa_id whose cross-references to follow."
                ),
            ),
            FunctionTool.from_defaults(
                fn=self._filter_by_topic,
                name="filter_by_topic",
                description=(
                    "Filter the most-recent search results to those whose topic_path "
                    "or source_url contains the given keyword. "
                    "Useful for scoping results to a specific EMA regulatory procedure "
                    "(e.g. 'worksharing', 'article-31', 'herbal'). "
                    "Args: topic (str) — substring to match against topic_path/source_url."
                ),
            ),
            FunctionTool.from_defaults(
                fn=self._answer,
                name="answer",
                description=(
                    "Submit the final answer. Call this when you have gathered sufficient "
                    "evidence from the retrieved Q&As to answer the question accurately. "
                    "The agent loop terminates after this call. "
                    "Args: text (str) — the complete answer text; "
                    "cited_qa_ids (str) — JSON-encoded list of qa_id strings cited."
                ),
                return_direct=True,
            ),
        ]

        llm = Anthropic(model=model)

        # Build system prompt — prepend few-shot context when provided (TASK-027.7)
        system_prompt: str | None = None
        if fewshot_context:
            system_prompt = fewshot_context

        # LlamaIndex 0.14+ uses a direct constructor (Workflow-based API).
        agent_kwargs: dict[str, Any] = {"tools": tools, "llm": llm, "verbose": False}
        if system_prompt:
            agent_kwargs["system_prompt"] = system_prompt
        self._agent = ReActAgent(**agent_kwargs)
        self._max_steps = max_steps

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def _get_bm25_retriever(self, k: int):
        """Lazy-init and cache the BM25 retriever to avoid rebuilding per call."""
        from harness.retrieve import make_bm25_retriever
        if self._bm25_retriever is None:
            self._bm25_retriever = make_bm25_retriever(self.index, k)
        return self._bm25_retriever

    def _search(self, query: str, k: int | None = None) -> str:
        k = int(k) if k is not None else self.k
        if self.retrieval_mode == "hybrid":
            # Use cached BM25 retriever to avoid rebuilding per call
            from harness.retrieve import _results_from_nodes, _rrf_fuse, make_dense_retriever
            bm25 = self._get_bm25_retriever(k)
            dense_results = _results_from_nodes(make_dense_retriever(self.index, k).retrieve(query))
            bm25_results = _results_from_nodes(bm25.retrieve(query))
            results = _rrf_fuse([dense_results, bm25_results], k)
        else:
            results = retrieve(self.index, query, mode=self.retrieval_mode, k=k)
        self._last_results = results
        if not results:
            return "No results found."
        lines: list[str] = []
        for qa_id, score, meta in results:
            node = get_node_by_id(self.index, qa_id)
            text = node.text if node else "(text unavailable)"
            source = meta.get("source_title") or meta.get("source_url") or "unknown"
            lines.append(
                f"[qa_id: {qa_id}] [score: {score:.4f}] [source: {source}]\n{text}"
            )
        return "\n\n---\n\n".join(lines)

    def _follow_cross_refs(self, qa_id: str) -> str:
        nodes = _follow_cross_refs_impl(self.index, qa_id)
        if not nodes:
            return f"No cross-references found for qa_id='{qa_id}'."
        lines: list[str] = []
        for node in nodes:
            source = node.metadata.get("source_title") or node.metadata.get("source_url") or "unknown"
            lines.append(
                f"[qa_id: {node.node_id}] [source: {source}]\n{node.text}"
            )
        return "\n\n---\n\n".join(lines)

    def _filter_by_topic(self, topic: str) -> str:
        keyword = topic.lower()
        filtered = [
            (qa_id, score, meta)
            for qa_id, score, meta in self._last_results
            if keyword in (meta.get("topic_path") or "").lower()
            or keyword in (meta.get("source_url") or "").lower()
        ]
        if not filtered:
            return (
                f"No results matched topic keyword '{topic}'. "
                f"All {len(self._last_results)} previous results retained."
            )
        self._last_results = filtered
        header = f"Filtered to {len(filtered)} result(s) matching '{topic}':"
        lines = [
            f"  [{i+1}] qa_id={qa_id}  source={meta.get('source_title') or meta.get('source_url','?')}"
            for i, (qa_id, _, meta) in enumerate(filtered)
        ]
        return header + "\n" + "\n".join(lines)

    def _answer(self, text: str, cited_qa_ids: str = "[]") -> str:
        try:
            ids: list[str] = json.loads(cited_qa_ids) if isinstance(cited_qa_ids, str) else list(cited_qa_ids)
        except (json.JSONDecodeError, TypeError):
            ids = [cited_qa_ids] if cited_qa_ids else []
        self._answer_store = {"text": text, "cited_qa_ids": ids}
        return text

    # ------------------------------------------------------------------
    # Public run interface
    # ------------------------------------------------------------------

    def run(self, question: str) -> AgentAnswer:
        """Run the agent loop on *question* and return a structured AgentAnswer."""
        return asyncio.run(self.arun(question))

    async def arun(self, question: str) -> AgentAnswer:
        """Async version of run()."""
        self._last_results = []
        self._answer_store = None

        # Log few-shot injection as a span attribute so it's visible in Phoenix (TASK-027.7)
        if self._fewshot_context:
            try:
                from opentelemetry import trace as _otel_trace
                _cur_span = _otel_trace.get_current_span()
                _cur_span.set_attribute("fewshot_injected", True)
                _cur_span.set_attribute("fewshot_context_len", len(self._fewshot_context))
            except Exception:
                pass

        handler = self._agent.run(
            user_msg=question,
            max_iterations=self._max_steps,
        )
        agent_output = await handler

        # Extract trajectory from AgentOutput tool_calls
        trajectory = self._extract_trajectory(agent_output)

        if self._answer_store is not None:
            return AgentAnswer(
                text=self._answer_store["text"],
                cited_qa_ids=self._answer_store["cited_qa_ids"],
                trajectory=trajectory,
            )

        # Fallback: agent finished without calling answer() tool
        cited = [qa_id for qa_id, _, _ in self._last_results[:3]]
        return AgentAnswer(
            text=str(agent_output.response),
            cited_qa_ids=cited,
            trajectory=trajectory,
        )

    def _extract_trajectory(self, agent_output=None) -> list[dict]:
        """Extract tool calls and response from AgentOutput."""
        trajectory: list[dict] = []
        if agent_output is None:
            return trajectory
        try:
            # Capture tool calls made during the run
            for tc in (agent_output.tool_calls or []):
                step: dict = {"type": "tool_call", "tool_name": tc.tool_name if hasattr(tc, "tool_name") else str(tc)}
                if hasattr(tc, "tool_kwargs"):
                    step["tool_kwargs"] = tc.tool_kwargs
                if hasattr(tc, "tool_output"):
                    step["tool_output"] = str(tc.tool_output)[:200]
                trajectory.append(step)
            # Append final response
            trajectory.append({"type": "response", "content": str(agent_output.response)[:300]})
        except Exception as exc:
            log.debug("Trajectory extraction error: %s", exc)
        return trajectory
