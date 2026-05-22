"""
ReAct (native LlamaIndex Workflow) with per-step Phoenix spans.

Unlike react.py (FunctionAgent-based), every agent action is a separate @step
producing a distinct Phoenix span.  This lets the HITL system label individual
tool calls and thoughts independently, not just the final answer.

Workflow::

    StartEvent ──────────────────────┐
                                     ↓
    ObservationEvent ────────→  think ──→ ThoughtEvent ──→ act ──→ ActionEvent ──→ observe
                                 │                                                      │
                                 └──→ FinishEvent ──→ finish ──→ StopEvent ←───────────┘
                                                                     (via observe loop)

Tools::
    ema_search <query>        — hybrid RRF retrieval; call this first
    follow_cross_refs <qa_id> — expand cross-referenced Q&A entries
    filter_by_topic <topic>   — narrow last docs_snapshot by topic/URL keyword
    get_qa_by_id <qa_id>      — fetch a specific Q&A entry by its ID

Usage::

    from harness.workflows.react_native import build_react_native
    from harness.llms import get_llm
    from harness.embed import build_index

    index  = build_index(corpus_path, index_dir)
    runner = build_react_native(index=index, llm=get_llm("agent"))
    result = runner.invoke({"question": "What is the AI for NDMA?"})
    print(result["answer_text"])
"""

from __future__ import annotations

import logging
from typing import Any

from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.workflow import Context, StartEvent, StopEvent, Workflow, step

from harness.retrieve import RetrievalConfig, retrieve_with_config
from harness.workflows.events import (
    ActionEvent,
    FinishEvent,
    ObservationEvent,
    ThoughtEvent,
)
from harness.workflows.utils import WorkflowRunner, results_to_docs

log = logging.getLogger(__name__)

MAX_ITERATIONS = 5

_SYSTEM_PROMPT = """\
You are an expert on European Medicines Agency (EMA) human-regulatory procedures.
Answer questions about EMA regulatory Q&As using the available tools.

Available tools:
  ema_search        — Search the EMA Q&A corpus using hybrid retrieval. Call this first.
  follow_cross_refs — Follow cross-references from a Q&A entry to related entries.
  filter_by_topic   — Filter last search results by topic path or source URL keyword.
  get_qa_by_id      — Fetch a specific Q&A entry by its ID.

Respond in this exact format:
  Thought: <your reasoning>
  Action: <tool_name>
  Action Input: <tool argument>

When you have gathered enough information to answer:
  Thought: <your final reasoning>
  Final Answer: <complete answer, citing qa_id values where relevant>

Always call ema_search before answering. Do not fabricate qa_id values.
"""


def _format_react_prompt(question: str, history: list) -> str:
    """Format question + accumulated history into a ReAct-style user message."""
    lines = [f"Question: {question}", ""]
    step_n = 0
    for entry in history:
        role = entry.get("role", "")
        if role == "thought":
            step_n += 1
            lines.append(f"[Step {step_n}]")
            lines.append(f"Thought: {entry.get('thought', '')}")
            if entry.get("tool"):
                lines.append(f"Action: {entry['tool']}")
                lines.append(f"Action Input: {entry.get('args', '')}")
        elif role == "observation":
            lines.append(f"Observation: {entry.get('content', '')[:600]}")
        lines.append("")
    lines.append("(Continue reasoning with the next Thought / Action / Final Answer)")
    return "\n".join(lines)


def _parse_thought(raw: str) -> tuple[str, str | None, str]:
    """
    Parse a ReAct-formatted LLM response.

    Returns:
        (thought, tool_name, tool_args_or_final_answer)

        tool_name is None when the agent produced a Final Answer line.
        In that case tool_args_or_final_answer holds the answer text.
    """
    thought = ""
    tool_name: str | None = None
    tool_args = ""
    final_answer: str | None = None

    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped.startswith("Thought:"):
            thought = stripped[len("Thought:"):].strip()
        elif stripped.startswith("Action:") and final_answer is None:
            tool_name = stripped[len("Action:"):].strip() or None
        elif stripped.startswith("Action Input:") and final_answer is None:
            tool_args = stripped[len("Action Input:"):].strip()
        elif stripped.startswith("Final Answer:"):
            final_answer = stripped[len("Final Answer:"):].strip()
            tool_name = None

    if final_answer is not None:
        return thought, None, final_answer

    if not thought and not tool_name:
        # Fallback: treat the entire response as a final answer
        return raw.strip(), None, raw.strip()

    return thought, tool_name, tool_args


def _format_docs(nodes: list) -> str:
    if not nodes:
        return "No results found."
    lines: list[str] = []
    for i, node in enumerate(nodes, 1):
        meta = node.metadata
        qa_id = meta.get("qa_id", "?")
        score = meta.get("score", 0.0)
        lines.append(f"[{i}] qa_id={qa_id} score={score:.3f}")
        lines.append(node.text[:400])
        lines.append("")
    return "\n".join(lines)


class ReActNativeWorkflow(Workflow):
    """
    Hand-written ReAct loop: each think/act/observe is a separate @step.

    Args:
        index:            LlamaIndex VectorStoreIndex.
        llm:              LlamaIndex LLM.
        retrieval_config: RetrievalConfig (defaults to flat hybrid k=10).
        max_iterations:   Max think-act-observe cycles before forcing an answer.
    """

    def __init__(
        self,
        *,
        index: Any,
        llm: Any,
        retrieval_config: RetrievalConfig | None = None,
        max_iterations: int = MAX_ITERATIONS,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._index = index
        self._llm = llm
        self._config = retrieval_config or RetrievalConfig()
        self._max_iterations = max_iterations
        # Apply A1 acronym expansion on ema_search queries (handles AI→Acceptable Intake etc.)
        try:
            from harness.ablations.a1_query_expansion import QueryExpander
            self._expander: Any = QueryExpander()
        except Exception:
            self._expander = None

    # ------------------------------------------------------------------
    # Step 1: Think
    # ------------------------------------------------------------------

    @step
    async def think(
        self, ctx: Context, ev: StartEvent | ObservationEvent
    ) -> ThoughtEvent | FinishEvent:
        if isinstance(ev, StartEvent):
            question: str = ev.get("question", "")
            iteration: int = 0
            history: list = []
            cited_qa_ids: list = []
            docs_snapshot: list = []
        else:
            question = ev.question
            iteration = ev.iteration
            history = list(ev.history)
            cited_qa_ids = list(ev.cited_qa_ids)
            docs_snapshot = list(ev.docs_snapshot)

        # Max iterations guard — force final answer from best available doc
        if iteration >= self._max_iterations:
            log.warning(
                "ReAct native: max iterations (%d) reached; forcing final answer",
                self._max_iterations,
            )
            best = (
                docs_snapshot[0].text if docs_snapshot
                else "Insufficient information retrieved after maximum search iterations."
            )
            return FinishEvent(
                answer_text=f"[Max iterations reached]\n{best}",
                cited_qa_ids=cited_qa_ids,
                docs=docs_snapshot,
                history=history,
            )

        prompt = _format_react_prompt(question, history)
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=_SYSTEM_PROMPT),
            ChatMessage(role=MessageRole.USER, content=prompt),
        ]
        response = await self._llm.achat(messages)
        raw: str = response.message.content or ""
        thought, tool_name, tool_args = _parse_thought(raw)

        log.debug(
            "ReAct think (iter=%d): thought=%r tool=%r args=%r",
            iteration, thought[:80], tool_name,
            (tool_args[:60] if tool_args else ""),
        )

        thought_entry: dict = {"role": "thought", "thought": thought}
        if tool_name:
            thought_entry.update({"tool": tool_name, "args": tool_args})
        history = history + [thought_entry]

        if tool_name is None:
            return FinishEvent(
                answer_text=tool_args,
                cited_qa_ids=cited_qa_ids,
                docs=docs_snapshot,
                history=history,
            )

        return ThoughtEvent(
            thought=thought,
            tool_name=tool_name,
            tool_args=tool_args,
            question=question,
            history=history,
            iteration=iteration,
            cited_qa_ids=cited_qa_ids,
            docs_snapshot=docs_snapshot,
        )

    # ------------------------------------------------------------------
    # Step 2: Act
    # ------------------------------------------------------------------

    @step
    async def act(self, ctx: Context, ev: ThoughtEvent) -> ActionEvent:
        tool_name = ev.tool_name or ""
        result, docs_snapshot, cited_qa_ids = await self._run_tool(
            tool_name, ev.tool_args, ev.docs_snapshot, ev.cited_qa_ids
        )

        log.debug(
            "ReAct act (iter=%d): tool=%r → %d chars result",
            ev.iteration, tool_name, len(result),
        )

        return ActionEvent(
            tool_name=tool_name,
            tool_result=result,
            docs_snapshot=docs_snapshot,
            question=ev.question,
            history=ev.history,
            iteration=ev.iteration,
            cited_qa_ids=cited_qa_ids,
        )

    # ------------------------------------------------------------------
    # Step 3: Observe
    # ------------------------------------------------------------------

    @step
    async def observe(self, ctx: Context, ev: ActionEvent) -> ObservationEvent:
        observation = ev.tool_result[:800]
        history = list(ev.history) + [{"role": "observation", "content": observation}]

        log.debug("ReAct observe (iter=%d): %d chars", ev.iteration, len(observation))

        return ObservationEvent(
            observation=observation,
            question=ev.question,
            history=history,
            iteration=ev.iteration + 1,
            cited_qa_ids=ev.cited_qa_ids,
            docs_snapshot=ev.docs_snapshot,
        )

    # ------------------------------------------------------------------
    # Step 4: Finish
    # ------------------------------------------------------------------

    @step
    async def finish(self, ctx: Context, ev: FinishEvent) -> StopEvent:
        return StopEvent(result={
            "answer_text": ev.answer_text or "No answer generated.",
            "docs": ev.docs,
            "cited_qa_ids": ev.cited_qa_ids,
            "trajectory": [e for e in ev.history if e.get("role") in ("thought", "observation")],
            "prompt_strategy": "react_native",
        })

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    async def _run_tool(
        self,
        tool_name: str,
        tool_args: str,
        docs_snapshot: list,
        cited_qa_ids: list,
    ) -> tuple[str, list, list]:
        if tool_name == "ema_search":
            query = tool_args.strip()
            if self._expander is not None:
                query = self._expander.expand(query)
            results = retrieve_with_config(self._config, self._index, query)
            docs = results_to_docs(results, self._index)
            return _format_docs(docs), docs, cited_qa_ids

        if tool_name == "follow_cross_refs":
            from harness.embed import follow_cross_refs as _follow
            nodes = _follow(self._index, tool_args.strip())
            if nodes:
                return _format_docs(nodes), nodes, cited_qa_ids
            return f"No cross-refs found for {tool_args.strip()!r}", docs_snapshot, cited_qa_ids

        if tool_name == "filter_by_topic":
            topic_lower = tool_args.strip().lower()
            filtered = [
                d for d in docs_snapshot
                if topic_lower in (d.metadata.get("topic_path") or "").lower()
                or topic_lower in (d.metadata.get("source_url") or "").lower()
            ]
            if filtered:
                return _format_docs(filtered), filtered, cited_qa_ids
            return f"No results after filtering by {tool_args.strip()!r}", docs_snapshot, cited_qa_ids

        if tool_name == "get_qa_by_id":
            from harness.embed import get_node_by_id
            qa_id = tool_args.strip()
            node = get_node_by_id(self._index, qa_id)
            new_cited = list(cited_qa_ids)
            if qa_id not in new_cited:
                new_cited.append(qa_id)
            if node:
                return node.text, docs_snapshot, new_cited
            return f"No entry found for qa_id={qa_id!r}", docs_snapshot, new_cited

        return (
            f"Unknown tool {tool_name!r}. Available: ema_search, follow_cross_refs, filter_by_topic, get_qa_by_id",
            docs_snapshot,
            cited_qa_ids,
        )


def build_react_native(
    *,
    index: Any,
    llm: Any,
    retrieval_config: RetrievalConfig | None = None,
    max_iterations: int = MAX_ITERATIONS,
) -> WorkflowRunner:
    """Factory function matching the registry interface."""
    wf = ReActNativeWorkflow(
        index=index,
        llm=llm,
        retrieval_config=retrieval_config,
        max_iterations=max_iterations,
        timeout=300,
    )
    return WorkflowRunner(wf)
