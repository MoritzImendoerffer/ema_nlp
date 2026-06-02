"""
Corrective RAG (CRAG) LlamaIndex Workflow.

Workflow::

    retrieve ──→ grade ──→ sufficient? ──yes──→ generate ──→ StopEvent
                    │
                    └── no ──→ rewrite ──→ retrieve (loop, max MAX_CYCLES)

Events:
    StartEvent        → retrieve (initial)
    _CRAGQueryEvent   → retrieve (loop — produced by rewrite step)
    RetrievedEvent    → grade
    GradeEvent        → generate        (grade == "sufficient" or max cycles)
    InsufficientEvent → rewrite
    StopEvent         ← generate

Grading uses per-doc 0/1/2 scoring with a JSON response::

    {
      "per_doc": [{"qa_id": "...", "score": 0|1|2}, ...],
      "missing_facts": ["what fact is missing", ...]
    }

Grade is "sufficient" when any doc scores 2 AND missing_facts is empty.
The rewrite prompt is grounded in missing_facts so queries target the actual gap.

Usage::

    from harness.workflows.crag import CRAGWorkflow
    from harness.workflows.utils import WorkflowRunner
    from harness.llms import get_llm
    from harness.embed import build_index

    index  = build_index(corpus_path, index_dir)
    llm    = get_llm("agent")
    runner = WorkflowRunner(CRAGWorkflow(index=index, llm=llm, timeout=180))
    result = runner.invoke({"question": "What is the AI for NDMA?"})
    print(result["answer_text"])
    print(result["rewrite_cycles_used"])
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.workflow import Context, Event, StartEvent, StopEvent, Workflow, step

from harness.workflows.events import GradeEvent, InsufficientEvent, RetrievedEvent
from harness.workflows.utils import (
    WorkflowRunner,
    build_rag_messages,
    extract_answer,
    format_docs,
    load_system_prompt,
    nodes_from_retrieval,
    retriever_attributes,
)

log = logging.getLogger(__name__)

MAX_CYCLES = 2  # max retrieve-rewrite iterations before forcing an answer

_GRADE_SYSTEM = """\
You are a relevance grader for EMA regulatory Q&A retrieval.

Score each retrieved document on a 0–2 scale:
  0 — not relevant; shares keywords but doesn't address the question
  1 — partially relevant; addresses the topic but misses key details
  2 — fully relevant; directly answers the question with specific information

Also list any facts the question requires that are absent from ALL retrieved documents.

Respond with ONLY valid JSON in this exact format:
{
  "per_doc": [
    {"qa_id": "<qa_id>", "score": <0|1|2>},
    ...
  ],
  "missing_facts": ["<description of missing fact>", ...]
}

If all necessary facts are covered (score=2 exists and nothing is missing), set missing_facts to [].
"""

_REWRITE_SYSTEM = """\
You are a query rewriter for EMA regulatory document retrieval.
The original query did not retrieve sufficient documents.

Rewrite the query to target the specific missing facts listed below.
Use precise EMA terminology. Return only the rewritten query — nothing else.
"""


def _parse_grade(raw: str) -> tuple[list[dict], list[str]]:
    """Parse grader JSON response. Returns (per_doc, missing_facts)."""
    # Strip markdown code fences
    raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    # Extract JSON object: take from first { to last }
    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        raw = raw[first_brace : last_brace + 1]
    try:
        data = json.loads(raw)
        per_doc: list[dict] = data.get("per_doc", [])
        missing_facts: list[str] = data.get("missing_facts", [])
        return per_doc, missing_facts
    except (json.JSONDecodeError, KeyError):
        log.warning("CRAG: could not parse grader JSON: %s", raw[:200])
        return [], ["(parse error — treating as insufficient)"]


def _is_sufficient(per_doc: list[dict], missing_facts: list[str]) -> bool:
    """Grade is sufficient when at least one doc scores 2 AND missing_facts is empty."""
    has_excellent = any(d.get("score", 0) == 2 for d in per_doc)
    return has_excellent and not missing_facts


class _CRAGQueryEvent(Event):
    """Internal loop event: carries a rewritten query back to the retrieve step."""
    question: str
    few_shot_context: str
    rewrite_cycles: int


class CRAGWorkflow(Workflow):
    """
    Corrective RAG: retrieve → grade ⇄ rewrite → generate.

    Args:
        retriever:        LlamaIndex BaseRetriever (HierarchicalPGRetriever).
        llm:              LlamaIndex LLM.
        prompt_strategy:  Answer generation strategy.
        max_cycles:       Max retrieve-rewrite cycles (default MAX_CYCLES=2).
    """

    def __init__(
        self,
        *,
        retriever: Any,
        llm: Any,
        prompt_strategy: str = "zero_shot",
        max_cycles: int = MAX_CYCLES,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._retriever = retriever
        self._llm = llm
        self._prompt_strategy = prompt_strategy
        self._max_cycles = max_cycles
        self._system_prompt = load_system_prompt(prompt_strategy)

    def config_attributes(self) -> dict:
        return {
            "ema.orchestration.strategy": "crag",
            "ema.orchestration.prompt_strategy": self._prompt_strategy,
            "ema.crag.max_cycles": self._max_cycles,
            **retriever_attributes(self._retriever),
        }

    # ------------------------------------------------------------------
    # Step 1: Retrieve
    # ------------------------------------------------------------------

    @step
    async def retrieve(
        self, ctx: Context, ev: StartEvent | _CRAGQueryEvent
    ) -> RetrievedEvent:
        if isinstance(ev, StartEvent):
            question: str = ev.get("question", "")
            few_shot_context: str = ev.get("few_shot_context", "")
            rewrite_cycles: int = 0
        else:
            question = ev.question
            few_shot_context = ev.few_shot_context
            rewrite_cycles = ev.rewrite_cycles

        docs = nodes_from_retrieval(await self._retriever.aretrieve(question))

        return RetrievedEvent(
            question=question,
            few_shot_context=few_shot_context,
            docs=docs,
            rewrite_cycles=rewrite_cycles,
        )

    # ------------------------------------------------------------------
    # Step 2: Grade document sufficiency (per-doc JSON scoring)
    # ------------------------------------------------------------------

    @step
    async def grade(
        self, ctx: Context, ev: RetrievedEvent
    ) -> GradeEvent | InsufficientEvent:
        context_str = format_docs(ev.docs)
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=_GRADE_SYSTEM),
            ChatMessage(
                role=MessageRole.USER,
                content=(
                    f"Question: {ev.question}\n\n"
                    f"Retrieved documents:\n{context_str}"
                ),
            ),
        ]
        response = await self._llm.achat(messages)
        raw = response.message.content or ""
        per_doc, missing_facts = _parse_grade(raw)
        sufficient = _is_sufficient(per_doc, missing_facts)

        log.debug(
            "CRAG grade (cycle=%d): %s | per_doc scores=%s | missing=%s",
            ev.rewrite_cycles,
            "sufficient" if sufficient else "insufficient",
            [d.get("score") for d in per_doc],
            missing_facts,
        )

        if sufficient or ev.rewrite_cycles >= self._max_cycles:
            if ev.rewrite_cycles >= self._max_cycles and not sufficient:
                log.warning(
                    "CRAG: max cycles (%d) reached; generating anyway. "
                    "per_doc=%s missing_facts=%s",
                    self._max_cycles, per_doc, missing_facts,
                )
            return GradeEvent(
                question=ev.question,
                few_shot_context=ev.few_shot_context,
                docs=ev.docs,
                rewrite_cycles=ev.rewrite_cycles,
                graded_docs=per_doc,
            )

        return InsufficientEvent(
            question=ev.question,
            few_shot_context=ev.few_shot_context,
            rewrite_cycles=ev.rewrite_cycles,
            missing_facts=missing_facts,
        )

    # ------------------------------------------------------------------
    # Step 3a: Generate (grade passed)
    # ------------------------------------------------------------------

    @step
    async def generate(self, ctx: Context, ev: GradeEvent) -> StopEvent:
        context_str = format_docs(ev.docs)
        messages = build_rag_messages(
            self._system_prompt, context_str, ev.question, ev.few_shot_context
        )
        response = await self._llm.achat(messages)
        raw: str = response.message.content or ""
        answer_text = extract_answer(raw, self._prompt_strategy)

        return StopEvent(result={
            "answer_text": answer_text,
            "docs": ev.docs,
            "prompt_strategy": f"crag_{self._prompt_strategy}",
            "rewrite_cycles_used": ev.rewrite_cycles,
            "graded_docs": ev.graded_docs,
        })

    # ------------------------------------------------------------------
    # Step 3b: Rewrite query (grade failed — grounded in missing_facts)
    # ------------------------------------------------------------------

    @step
    async def rewrite(self, ctx: Context, ev: InsufficientEvent) -> _CRAGQueryEvent:
        missing_str = "\n".join(f"- {f}" for f in ev.missing_facts) or "(unspecified)"
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=_REWRITE_SYSTEM),
            ChatMessage(
                role=MessageRole.USER,
                content=(
                    f"Original query: {ev.question}\n\n"
                    f"Missing facts that the retrieved documents do not cover:\n{missing_str}"
                ),
            ),
        ]
        response = await self._llm.achat(messages)
        new_question = (response.message.content or ev.question).strip()

        log.debug(
            "CRAG rewrite (cycle %d→%d): %r → %r",
            ev.rewrite_cycles,
            ev.rewrite_cycles + 1,
            ev.question[:60],
            new_question[:60],
        )

        return _CRAGQueryEvent(
            question=new_question,
            few_shot_context=ev.few_shot_context,
            rewrite_cycles=ev.rewrite_cycles + 1,
        )


def build_crag(
    *,
    retriever: Any,
    llm: Any,
    prompt_strategy: str = "zero_shot",
) -> WorkflowRunner:
    """Factory function matching the registry interface."""
    wf = CRAGWorkflow(
        retriever=retriever,
        llm=llm,
        prompt_strategy=prompt_strategy,
        timeout=300,
    )
    return WorkflowRunner(wf)
