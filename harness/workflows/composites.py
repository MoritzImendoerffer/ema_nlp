"""
Composite LlamaIndex Workflow strategies combining CRAG, summarization, and review.

Three composite workflows:
    CRAGSummarizeWorkflow  — CRAG retrieval loop + document summarization before generation
    CRAGReviewWorkflow     — CRAG retrieval loop + faithfulness review after generation
    ReactReviewWorkflow    — ReAct agent answer + single faithfulness review pass

Event flow:

  CRAGSummarize:
    StartEvent → retrieve → RetrievedEvent → grade
      → GradeEvent → summarize → SummarizedEvent → generate → StopEvent
      → InsufficientEvent → rewrite → _SumQueryEvent → retrieve (loop)

  CRAGReview:
    StartEvent → retrieve → RetrievedEvent → grade
      → GradeEvent → generate → GeneratedEvent → review → StopEvent
      → InsufficientEvent → rewrite → _RevQueryEvent → retrieve (loop)

  ReactReview:
    StartEvent → run_react → GeneratedEvent → review → StopEvent
"""

from __future__ import annotations

import logging
from typing import Any

from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.workflow import Context, Event, StartEvent, StopEvent, Workflow, step

from harness.workflows.events import (
    GeneratedEvent,
    GradeEvent,
    InsufficientEvent,
    RetrievedEvent,
    SummarizedEvent,
)
from harness.workflows.review import run_review_step
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

MAX_CYCLES = 2

_GRADE_SYSTEM = (
    "You are a relevance grader for EMA regulatory Q&A retrieval. "
    "Decide whether the retrieved documents contain enough information to answer the question.\n"
    "Respond with exactly one word: 'sufficient' or 'insufficient'. Do not explain."
)
_REWRITE_SYSTEM = (
    "You are a query rewriter for EMA regulatory document retrieval. "
    "The original query did not retrieve sufficient documents. "
    "Rewrite it to be more specific, using EMA terminology. "
    "Return only the rewritten query, nothing else."
)


# ---------------------------------------------------------------------------
# CRAGSummarizeWorkflow
# ---------------------------------------------------------------------------

class _SumQueryEvent(Event):
    """Internal loop event for CRAGSummarize."""
    question: str
    few_shot_context: str
    rewrite_cycles: int


class CRAGSummarizeWorkflow(Workflow):
    """CRAG retrieval loop followed by document summarization before generation."""

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
        from pathlib import Path
        _prompts = Path(__file__).parent.parent / "prompts"
        self._summarize_prompt = (_prompts / "system_summarize.md").read_text(encoding="utf-8")

    def config_attributes(self) -> dict:
        return {
            "ema.orchestration.strategy": "crag_summarize",
            "ema.orchestration.prompt_strategy": self._prompt_strategy,
            "ema.crag.max_cycles": self._max_cycles,
            **retriever_attributes(self._retriever),
        }

    @step
    async def retrieve(self, ctx: Context, ev: StartEvent | _SumQueryEvent) -> RetrievedEvent:
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
            question=question, few_shot_context=few_shot_context,
            docs=docs, rewrite_cycles=rewrite_cycles,
        )

    @step
    async def grade(self, ctx: Context, ev: RetrievedEvent) -> GradeEvent | InsufficientEvent:
        context_str = format_docs(ev.docs)
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=_GRADE_SYSTEM),
            ChatMessage(role=MessageRole.USER, content=(
                f"Question: {ev.question}\n\nDocuments:\n{context_str}\n\n"
                "Are these documents sufficient to answer the question?"
            )),
        ]
        response = await self._llm.achat(messages)
        raw = (response.message.content or "").lower().strip()
        sufficient = "sufficient" in raw and "insufficient" not in raw
        if sufficient or ev.rewrite_cycles >= self._max_cycles:
            return GradeEvent(
                question=ev.question, few_shot_context=ev.few_shot_context,
                docs=ev.docs, rewrite_cycles=ev.rewrite_cycles,
            )
        return InsufficientEvent(
            question=ev.question, few_shot_context=ev.few_shot_context,
            rewrite_cycles=ev.rewrite_cycles,
        )

    @step
    async def summarize(self, ctx: Context, ev: GradeEvent) -> SummarizedEvent:
        context_str = format_docs(ev.docs)
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=self._summarize_prompt),
            ChatMessage(role=MessageRole.USER, content=(
                f"QUESTION: {ev.question}\n\nRELEVANT DOCUMENTS:\n{context_str}"
            )),
        ]
        response = await self._llm.achat(messages)
        summary = (response.message.content or "").strip()
        return SummarizedEvent(
            summary=summary, docs=ev.docs,
            question=ev.question, few_shot_context=ev.few_shot_context,
        )

    @step
    async def generate(self, ctx: Context, ev: SummarizedEvent) -> StopEvent:
        context_str = ev.summary if ev.summary else format_docs(ev.docs)
        messages = build_rag_messages(
            self._system_prompt, context_str, ev.question, ev.few_shot_context
        )
        response = await self._llm.achat(messages)
        raw: str = response.message.content or ""
        answer_text = extract_answer(raw, self._prompt_strategy)
        return StopEvent(result={
            "answer_text": answer_text,
            "docs": ev.docs,
            "summary": ev.summary,
            "prompt_strategy": f"crag_summarize_{self._prompt_strategy}",
        })

    @step
    async def rewrite(self, ctx: Context, ev: InsufficientEvent) -> _SumQueryEvent:
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=_REWRITE_SYSTEM),
            ChatMessage(role=MessageRole.USER, content=f"Original query: {ev.question}"),
        ]
        response = await self._llm.achat(messages)
        new_question = (response.message.content or ev.question).strip()
        return _SumQueryEvent(
            question=new_question, few_shot_context=ev.few_shot_context,
            rewrite_cycles=ev.rewrite_cycles + 1,
        )


# ---------------------------------------------------------------------------
# CRAGReviewWorkflow
# ---------------------------------------------------------------------------

class _RevQueryEvent(Event):
    """Internal loop event for CRAGReview."""
    question: str
    few_shot_context: str
    rewrite_cycles: int


class _RevGradeEvent(Event):
    """Internal grade-passed event for CRAGReview (routes to generate, not StopEvent)."""
    question: str
    few_shot_context: str
    docs: list
    rewrite_cycles: int


class CRAGReviewWorkflow(Workflow):
    """CRAG retrieval loop followed by a faithfulness review after generation."""

    def __init__(
        self,
        *,
        retriever: Any,
        llm: Any,
        prompt_strategy: str = "zero_shot",
        max_cycles: int = MAX_CYCLES,
        review_threshold: float = 0.6,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._retriever = retriever
        self._llm = llm
        self._prompt_strategy = prompt_strategy
        self._max_cycles = max_cycles
        self._review_threshold = review_threshold
        self._system_prompt = load_system_prompt(prompt_strategy)

    def config_attributes(self) -> dict:
        return {
            "ema.orchestration.strategy": "crag_review",
            "ema.orchestration.prompt_strategy": self._prompt_strategy,
            "ema.crag.max_cycles": self._max_cycles,
            **retriever_attributes(self._retriever),
        }

    @step
    async def retrieve(self, ctx: Context, ev: StartEvent | _RevQueryEvent) -> RetrievedEvent:
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
            question=question, few_shot_context=few_shot_context,
            docs=docs, rewrite_cycles=rewrite_cycles,
        )

    @step
    async def grade(self, ctx: Context, ev: RetrievedEvent) -> _RevGradeEvent | InsufficientEvent:
        context_str = format_docs(ev.docs)
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=_GRADE_SYSTEM),
            ChatMessage(role=MessageRole.USER, content=(
                f"Question: {ev.question}\n\nDocuments:\n{context_str}\n\n"
                "Are these documents sufficient to answer the question?"
            )),
        ]
        response = await self._llm.achat(messages)
        raw = (response.message.content or "").lower().strip()
        sufficient = "sufficient" in raw and "insufficient" not in raw
        if sufficient or ev.rewrite_cycles >= self._max_cycles:
            return _RevGradeEvent(
                question=ev.question, few_shot_context=ev.few_shot_context,
                docs=ev.docs, rewrite_cycles=ev.rewrite_cycles,
            )
        return InsufficientEvent(
            question=ev.question, few_shot_context=ev.few_shot_context,
            rewrite_cycles=ev.rewrite_cycles,
        )

    @step
    async def generate(self, ctx: Context, ev: _RevGradeEvent) -> GeneratedEvent:
        context_str = format_docs(ev.docs)
        messages = build_rag_messages(
            self._system_prompt, context_str, ev.question, ev.few_shot_context
        )
        response = await self._llm.achat(messages)
        raw: str = response.message.content or ""
        answer_text = extract_answer(raw, self._prompt_strategy)
        return GeneratedEvent(
            answer_text=answer_text,
            docs=ev.docs,
            question=ev.question,
            prompt_strategy=f"crag_review_{self._prompt_strategy}",
        )

    @step
    async def review(self, ctx: Context, ev: GeneratedEvent) -> StopEvent:
        reviewed = await run_review_step(ev, threshold=self._review_threshold)
        return StopEvent(result={
            "answer_text": reviewed.answer_text,
            "docs": reviewed.docs,
            "prompt_strategy": ev.prompt_strategy,
            "review_score": reviewed.score,
            "review_feedback": reviewed.feedback,
        })

    @step
    async def rewrite(self, ctx: Context, ev: InsufficientEvent) -> _RevQueryEvent:
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=_REWRITE_SYSTEM),
            ChatMessage(role=MessageRole.USER, content=f"Original query: {ev.question}"),
        ]
        response = await self._llm.achat(messages)
        new_question = (response.message.content or ev.question).strip()
        return _RevQueryEvent(
            question=new_question, few_shot_context=ev.few_shot_context,
            rewrite_cycles=ev.rewrite_cycles + 1,
        )


# ---------------------------------------------------------------------------
# ReactReviewWorkflow
# ---------------------------------------------------------------------------

class ReactReviewWorkflow(Workflow):
    """ReAct agent answer followed by a single faithfulness review pass (no revision)."""

    def __init__(
        self,
        *,
        retriever: Any,
        llm: Any,
        review_threshold: float = 0.6,
        max_iterations: int = 10,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        from harness.workflows.react_native import build_react_native
        self._react = build_react_native(
            retriever=retriever,
            llm=llm,
            max_iterations=max_iterations,
        )
        self._review_threshold = review_threshold
        self._retriever = retriever

    def config_attributes(self) -> dict:
        return {
            "ema.orchestration.strategy": "react_review",
            "ema.orchestration.prompt_strategy": "react_native",
            **retriever_attributes(self._retriever),
        }

    @step
    async def run_react(self, ctx: Context, ev: StartEvent) -> GeneratedEvent:
        question: str = ev.get("question", "")
        result = await self._react.ainvoke({"question": question})
        return GeneratedEvent(
            answer_text=result.get("answer_text", "No answer generated."),
            docs=result.get("docs", []),
            question=question,
            prompt_strategy="react_review",
        )

    @step
    async def review(self, ctx: Context, ev: GeneratedEvent) -> StopEvent:
        reviewed = await run_review_step(ev, threshold=self._review_threshold)
        return StopEvent(result={
            "answer_text": reviewed.answer_text,
            "docs": reviewed.docs,
            "prompt_strategy": "react_review",
            "review_score": reviewed.score,
            "review_feedback": reviewed.feedback,
        })


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def build_crag_summarize(
    *,
    retriever: Any,
    llm: Any,
    prompt_strategy: str = "zero_shot",
) -> WorkflowRunner:
    wf = CRAGSummarizeWorkflow(
        retriever=retriever, llm=llm, prompt_strategy=prompt_strategy, timeout=300,
    )
    return WorkflowRunner(wf)


def build_crag_review(
    *,
    retriever: Any,
    llm: Any,
    prompt_strategy: str = "zero_shot",
    review_threshold: float = 0.6,
) -> WorkflowRunner:
    wf = CRAGReviewWorkflow(
        retriever=retriever, llm=llm, prompt_strategy=prompt_strategy,
        review_threshold=review_threshold,
        timeout=300,
    )
    return WorkflowRunner(wf)


def build_react_review(
    *,
    retriever: Any,
    llm: Any,
    review_threshold: float = 0.6,
) -> WorkflowRunner:
    wf = ReactReviewWorkflow(
        retriever=retriever, llm=llm,
        review_threshold=review_threshold,
        timeout=300,
    )
    return WorkflowRunner(wf)
