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
    ema_search <query>      — hierarchical Neo4j retrieval; call this first
    filter_by_topic <topic> — narrow last docs_snapshot by topic/URL keyword

Usage::

    from harness.workflows.react_native import build_react_native
    from harness.llms import get_llm
    from harness.indexing import load_index_profile
    from harness.indexing.property_graph import open_index
    from harness.indexing.registry import build_retriever

    profile   = load_index_profile()
    retriever = build_retriever(profile, open_index(profile))
    runner = build_react_native(retriever=retriever, llm=get_llm("agent"))
    result = runner.invoke({"question": "What is the AI for NDMA?"})
    print(result["answer_text"])
"""

from __future__ import annotations

import logging
from typing import Any

from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.workflow import Context, StartEvent, StopEvent, Workflow, step

from harness.workflows.events import (
    ActionEvent,
    FinishEvent,
    ObservationEvent,
    ThoughtEvent,
)
from harness.workflows.utils import (
    WorkflowRunner,
    nodes_from_retrieval,
    retriever_attributes,
)

log = logging.getLogger(__name__)

MAX_ITERATIONS = 5

_SYSTEM_PROMPT = """\
You are an expert on European Medicines Agency (EMA) human-regulatory procedures.
Answer questions by using the available tools to retrieve EMA regulatory Q&As.

Available tools:
  ema_search      — Search the EMA regulatory corpus using hierarchical retrieval.
  filter_by_topic — Filter last search results by topic path or source URL keyword.

REQUIREMENT: You MUST call ema_search at least once before writing "Final Answer:".
Do NOT write "Final Answer:" on your first response. Always begin with a tool call.

Use this exact format every response:
  Thought: <your reasoning about what to search for>
  Action: <tool_name>
  Action Input: <tool argument>

After you have retrieved sufficient information:
  Thought: <your synthesis reasoning>
  Final Answer: <complete multi-sentence answer, citing the source URLs of the documents you used>

Do not fabricate source URLs. Every source must come from a tool result.
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

        tool_name is None when the agent produced a Final Answer.
        In that case tool_args_or_final_answer holds the full answer text
        (everything after "Final Answer:", including multiple lines).
    """
    thought = ""
    tool_name: str | None = None
    tool_args = ""

    # Final Answer: captures everything from that marker to end-of-response,
    # preserving multi-line content.  Look for the marker case-insensitively
    # on any line.
    fa_marker = "Final Answer:"
    fa_pos = raw.find(fa_marker)
    if fa_pos == -1:
        # Try case-insensitive fallback
        lower = raw.lower()
        fa_pos = lower.find(fa_marker.lower())

    if fa_pos != -1:
        final_answer = raw[fa_pos + len(fa_marker):].strip()
        # Parse Thought from the preamble (before Final Answer)
        for line in raw[:fa_pos].split("\n"):
            stripped = line.strip()
            if stripped.startswith("Thought:"):
                thought = stripped[len("Thought:"):].strip()
        return thought, None, final_answer

    # No Final Answer marker — parse Thought/Action/Action Input
    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped.startswith("Thought:"):
            thought = stripped[len("Thought:"):].strip()
        elif stripped.startswith("Action:"):
            tool_name = stripped[len("Action:"):].strip() or None
        elif stripped.startswith("Action Input:"):
            tool_args = stripped[len("Action Input:"):].strip()

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
        source = meta.get("source_url", "?")
        score = meta.get("score", 0.0)
        lines.append(f"[{i}] source={source} score={score:.3f}")
        lines.append(node.text[:400])
        lines.append("")
    return "\n".join(lines)


class ReActNativeWorkflow(Workflow):
    """
    Hand-written ReAct loop: each think/act/observe is a separate @step.

    Args:
        retriever:        LlamaIndex BaseRetriever (HierarchicalPGRetriever).
        llm:              LlamaIndex LLM.
        max_iterations:   Max think-act-observe cycles before forcing an answer.
    """

    def __init__(
        self,
        *,
        retriever: Any,
        llm: Any,
        max_iterations: int = MAX_ITERATIONS,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._retriever = retriever
        self._llm = llm
        self._max_iterations = max_iterations
        # Apply A1 acronym expansion on ema_search queries (handles AI→Acceptable Intake etc.)
        try:
            from harness.ablations.a1_query_expansion import QueryExpander
            self._expander: Any = QueryExpander()
        except Exception:
            self._expander = None

    def config_attributes(self) -> dict:
        return {
            "ema.orchestration.strategy": "react",
            "ema.orchestration.prompt_strategy": "react_native",
            "ema.react.max_iterations": self._max_iterations,
            **retriever_attributes(self._retriever),
        }

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
        # On the first iteration, prefill the assistant turn with "Thought:" to
        # steer the model into the structured format and prevent it from jumping
        # straight to a Final Answer without calling any tools.
        if iteration == 0:
            messages.append(ChatMessage(role=MessageRole.ASSISTANT, content="Thought:"))
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
            docs = nodes_from_retrieval(await self._retriever.aretrieve(query))
            return _format_docs(docs), docs, cited_qa_ids

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

        return (
            f"Unknown tool {tool_name!r}. Available: ema_search, filter_by_topic",
            docs_snapshot,
            cited_qa_ids,
        )


def build_react_native(
    *,
    retriever: Any,
    llm: Any,
    max_iterations: int = MAX_ITERATIONS,
    **_: Any,  # tolerate forwarded kwargs (e.g. prompt_strategy) — ReAct ignores them
) -> WorkflowRunner:
    """Factory function matching the registry interface."""
    wf = ReActNativeWorkflow(
        retriever=retriever,
        llm=llm,
        max_iterations=max_iterations,
        timeout=300,
    )
    return WorkflowRunner(wf)
