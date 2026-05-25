"""
Summarize RAG LlamaIndex Workflow: retrieve → summarize → generate.

Summarization condenses retrieved documents into a ~200-word summary
before passing to the generator, reducing token load on the generator.

Events::

    StartEvent → retrieve → RetrievedEvent → summarize → SummarizedEvent → generate → StopEvent

Output::

    {"answer_text": str, "docs": list, "summary": str, "prompt_strategy": str}
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.workflow import Context, StartEvent, StopEvent, Workflow, step

from harness.retrieve import RetrievalConfig, retrieve_with_config
from harness.workflows.events import RetrievedEvent, SummarizedEvent
from harness.workflows.utils import (
    WorkflowRunner,
    build_rag_messages,
    extract_answer,
    format_docs,
    load_system_prompt,
    results_to_docs,
)

log = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class SummarizeRAGWorkflow(Workflow):
    """
    Summarize RAG: retrieve → summarize → generate.

    Args:
        index:            LlamaIndex VectorStoreIndex.
        llm:              LlamaIndex LLM.
        strategy:         Answer generation strategy ("zero_shot" etc.).
        retrieval_config: RetrievalConfig (defaults to flat hybrid k=10).
    """

    def __init__(
        self,
        *,
        index: Any,
        llm: Any,
        prompt_strategy: str = "zero_shot",
        retrieval_config: RetrievalConfig | None = None,
        retrieve_fn: Any | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._index = index
        self._llm = llm
        self._prompt_strategy = prompt_strategy
        self._config = retrieval_config or RetrievalConfig()
        self._retrieve_fn = retrieve_fn
        self._system_prompt = load_system_prompt(prompt_strategy)
        self._summarize_prompt = (_PROMPTS_DIR / "system_summarize.md").read_text(encoding="utf-8")

    def config_attributes(self) -> dict:
        abl = getattr(self._retrieve_fn, "ablation_config", None)
        return {
            "ema.orchestration.strategy": "summarize_rag",
            "ema.orchestration.prompt_strategy": self._prompt_strategy,
            "ema.retrieval.strategy": self._config.strategy,
            "ema.retrieval.mode": self._config.mode,
            "ema.retrieval.k": self._config.k,
            "ema.retrieval.reranker": abl.reranker or "none" if abl else "none",
            "ema.retrieval.query_expansion": abl.query_expansion_enabled if abl else False,
            "ema.retrieval.topic_filter": abl.topic_filter_mode or "none" if abl else "none",
        }

    @step
    async def retrieve(self, ctx: Context, ev: StartEvent) -> RetrievedEvent:
        question: str = ev.get("question", "")
        few_shot_context: str = ev.get("few_shot_context", "")

        results = (
            self._retrieve_fn(question)
            if self._retrieve_fn is not None
            else retrieve_with_config(self._config, self._index, question)
        )
        docs = results_to_docs(results, self._index)

        return RetrievedEvent(
            question=question,
            few_shot_context=few_shot_context,
            docs=docs,
        )

    @step
    async def summarize(self, ctx: Context, ev: RetrievedEvent) -> SummarizedEvent:
        if not ev.docs:
            log.debug("SummarizeRAG: no docs — skipping summarization")
            return SummarizedEvent(
                summary="",
                docs=ev.docs,
                question=ev.question,
                few_shot_context=ev.few_shot_context,
            )

        context_str = format_docs(ev.docs)
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=self._summarize_prompt),
            ChatMessage(
                role=MessageRole.USER,
                content=f"QUESTION: {ev.question}\n\nRELEVANT DOCUMENTS:\n{context_str}",
            ),
        ]
        response = await self._llm.achat(messages)
        summary = (response.message.content or "").strip()

        log.debug(
            "SummarizeRAG: %d chars summary from %d docs", len(summary), len(ev.docs)
        )
        return SummarizedEvent(
            summary=summary,
            docs=ev.docs,
            question=ev.question,
            few_shot_context=ev.few_shot_context,
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
            "prompt_strategy": f"summarize_{self._prompt_strategy}",
        })


def build_summarize_rag(
    *,
    index: Any,
    llm: Any,
    prompt_strategy: str = "zero_shot",
    retrieval_config: RetrievalConfig | None = None,
    retrieve_fn: Any | None = None,
) -> WorkflowRunner:
    """Factory function matching the registry interface."""
    wf = SummarizeRAGWorkflow(
        index=index,
        llm=llm,
        prompt_strategy=prompt_strategy,
        retrieval_config=retrieval_config,
        retrieve_fn=retrieve_fn,
        timeout=180,
    )
    return WorkflowRunner(wf)
