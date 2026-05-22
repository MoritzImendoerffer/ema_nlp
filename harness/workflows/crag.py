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

Usage::

    from harness.workflows.crag import CRAGWorkflow
    from harness.workflows.utils import WorkflowRunner
    from harness.llms import get_llm
    from harness.embed import build_index

    index  = build_index(corpus_path, index_dir)
    llm    = get_llm("frontier")
    runner = WorkflowRunner(CRAGWorkflow(index=index, llm=llm, timeout=180))
    result = runner.invoke({"question": "What is the AI for NDMA?"})
    print(result["answer_text"])
    print(result["rewrite_cycles_used"])
"""

from __future__ import annotations

import logging
from typing import Any

from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.workflow import Context, StartEvent, StopEvent, Workflow, step

from harness.retrieve import RetrievalConfig, retrieve_with_config
from llama_index.core.workflow import Event

from harness.workflows.events import GradeEvent, InsufficientEvent, RetrievedEvent
from harness.workflows.utils import (
    Doc,
    WorkflowRunner,
    build_rag_messages,
    extract_answer,
    format_docs,
    load_system_prompt,
    results_to_docs,
)

log = logging.getLogger(__name__)

MAX_CYCLES = 2  # max retrieve-rewrite iterations before forcing an answer

_GRADE_SYSTEM = (
    "You are a relevance grader for EMA regulatory Q&A retrieval. "
    "Your only job is to decide whether the retrieved documents contain "
    "enough information to answer the question.\n\n"
    "Respond with exactly one word: 'sufficient' or 'insufficient'.\n"
    "Do not explain your reasoning."
)

_REWRITE_SYSTEM = (
    "You are a query rewriter for EMA regulatory document retrieval. "
    "The original query did not retrieve sufficient documents. "
    "Rewrite it to be more specific, using EMA terminology. "
    "Return only the rewritten query, nothing else."
)


class _CRAGQueryEvent(Event):
    """Internal loop event: carries a rewritten query back to the retrieve step.

    Kept separate from RetrievedEvent so the router sends it to `retrieve`,
    not to `grade` (which consumes RetrievedEvent).
    """
    question: str
    few_shot_context: str
    rewrite_cycles: int


class CRAGWorkflow(Workflow):
    """
    Corrective RAG: retrieve → grade ⇄ rewrite → generate.

    Args:
        index:            LlamaIndex VectorStoreIndex.
        llm:              LlamaIndex LLM.
        strategy:         Answer generation strategy.
        retrieval_config: RetrievalConfig (defaults to flat hybrid k=10).
        max_cycles:       Max retrieve-rewrite cycles (default MAX_CYCLES=2).
    """

    def __init__(
        self,
        *,
        index: Any,
        llm: Any,
        strategy: str = "zero_shot",
        retrieval_config: RetrievalConfig | None = None,
        max_cycles: int = MAX_CYCLES,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._index = index
        self._llm = llm
        self._strategy = strategy
        self._config = retrieval_config or RetrievalConfig()
        self._max_cycles = max_cycles
        self._system_prompt = load_system_prompt(strategy)

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

        results = retrieve_with_config(self._config, self._index, question)
        docs: list[Doc] = results_to_docs(results, self._index)

        return RetrievedEvent(
            question=question,
            few_shot_context=few_shot_context,
            docs=docs,
            rewrite_cycles=rewrite_cycles,
        )

    # ------------------------------------------------------------------
    # Step 2: Grade document sufficiency
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
                    f"Retrieved documents:\n{context_str}\n\n"
                    "Are these documents sufficient to answer the question?"
                ),
            ),
        ]
        response = await self._llm.achat(messages)
        raw = (response.message.content or "").lower().strip()
        is_sufficient = "sufficient" in raw and "insufficient" not in raw

        log.debug(
            "CRAG grade (cycle=%d): %s",
            ev.rewrite_cycles,
            "sufficient" if is_sufficient else "insufficient",
        )

        if is_sufficient or ev.rewrite_cycles >= self._max_cycles:
            if ev.rewrite_cycles >= self._max_cycles and not is_sufficient:
                log.warning(
                    "CRAG: max cycles (%d) reached; generating anyway", self._max_cycles
                )
            return GradeEvent(
                question=ev.question,
                few_shot_context=ev.few_shot_context,
                docs=ev.docs,
                rewrite_cycles=ev.rewrite_cycles,
            )

        return InsufficientEvent(
            question=ev.question,
            few_shot_context=ev.few_shot_context,
            rewrite_cycles=ev.rewrite_cycles,
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
        answer_text = extract_answer(raw, self._strategy)

        return StopEvent(result={
            "answer_text": answer_text,
            "docs": ev.docs,
            "prompt_strategy": f"crag_{self._strategy}",
            "rewrite_cycles_used": ev.rewrite_cycles,
        })

    # ------------------------------------------------------------------
    # Step 3b: Rewrite query (grade failed)
    # ------------------------------------------------------------------

    @step
    async def rewrite(self, ctx: Context, ev: InsufficientEvent) -> _CRAGQueryEvent:
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=_REWRITE_SYSTEM),
            ChatMessage(role=MessageRole.USER, content=f"Original query: {ev.question}"),
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
            docs=[],  # filled by retrieve
            rewrite_cycles=ev.rewrite_cycles + 1,
        )


def build_crag(
    *,
    index: Any,
    llm: Any,
    strategy: str = "zero_shot",
    retrieval_config: RetrievalConfig | None = None,
) -> WorkflowRunner:
    """Factory function matching the registry interface."""
    wf = CRAGWorkflow(
        index=index,
        llm=llm,
        strategy=strategy,
        retrieval_config=retrieval_config,
        timeout=300,
    )
    return WorkflowRunner(wf)
