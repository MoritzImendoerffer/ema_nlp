"""
Simple RAG LlamaIndex Workflow: retrieve → generate (single step).

Three prompt strategies supported:
    zero_shot  — base instruction, no examples (system_zero_shot.md)
    few_shot   — SME-written Q&A examples prepended (system_few_shot_sme.md)
    cot_self   — Medprompt-style CoT: model reasons inside <reasoning> tags

The workflow accepts StartEvent(question, few_shot_context?) and returns:
    {"answer_text": str, "docs": list, "prompt_strategy": str}

Usage::

    from harness.workflows.simple_rag import SimpleRAGWorkflow
    from harness.workflows.utils import WorkflowRunner
    from harness.llms import get_llm
    from harness.embed import build_index
    from harness.retrieve import RetrievalConfig

    index = build_index(corpus_path, index_dir)
    llm   = get_llm("frontier")
    wf    = WorkflowRunner(SimpleRAGWorkflow(index=index, llm=llm, strategy="cot_self"))
    result = wf.invoke({"question": "What is the AI for NDMA?"})
"""

from __future__ import annotations

import logging
from typing import Any

from llama_index.core.workflow import Context, StartEvent, StopEvent, Workflow, step

from harness.retrieve import RetrievalConfig, retrieve_with_config
from harness.workflows.utils import (
    WorkflowRunner,
    build_rag_messages,
    extract_answer,
    format_docs,
    load_system_prompt,
    results_to_docs,
)

log = logging.getLogger(__name__)

_VALID_STRATEGIES = {"zero_shot", "few_shot", "cot_self"}


class SimpleRAGWorkflow(Workflow):
    """
    Single-step RAG: retrieve → generate.

    Args:
        index:            LlamaIndex VectorStoreIndex.
        llm:              LlamaIndex LLM (from harness.llms.get_llm).
        prompt_strategy:  "zero_shot" | "few_shot" | "cot_self".
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
        if prompt_strategy not in _VALID_STRATEGIES:
            raise ValueError(f"Unknown prompt_strategy {prompt_strategy!r}. Choose from: {_VALID_STRATEGIES}")
        self._index = index
        self._llm = llm
        self._prompt_strategy = prompt_strategy
        self._config = retrieval_config or RetrievalConfig()
        self._retrieve_fn = retrieve_fn
        self._system_prompt = load_system_prompt(prompt_strategy)

    def config_attributes(self) -> dict:
        abl = getattr(self._retrieve_fn, "ablation_config", None)
        return {
            "ema.orchestration.strategy": "simple_rag",
            "ema.orchestration.prompt_strategy": self._prompt_strategy,
            "ema.retrieval.strategy": self._config.strategy,
            "ema.retrieval.mode": self._config.mode,
            "ema.retrieval.k": self._config.k,
            "ema.retrieval.reranker": abl.reranker or "none" if abl else "none",
            "ema.retrieval.query_expansion": abl.query_expansion_enabled if abl else False,
            "ema.retrieval.topic_filter": abl.topic_filter_mode or "none" if abl else "none",
        }

    @step
    async def retrieve_and_generate(self, ctx: Context, ev: StartEvent) -> StopEvent:
        question: str = ev.get("question", "")
        few_shot_context: str = ev.get("few_shot_context", "")

        results = (
            self._retrieve_fn(question)
            if self._retrieve_fn is not None
            else retrieve_with_config(self._config, self._index, question)
        )
        docs = results_to_docs(results, self._index)
        context_str = format_docs(docs)

        messages = build_rag_messages(
            self._system_prompt, context_str, question, few_shot_context
        )
        response = await self._llm.achat(messages)
        raw: str = response.message.content or ""
        answer_text = extract_answer(raw, self._prompt_strategy)

        return StopEvent(result={
            "answer_text": answer_text,
            "docs": docs,
            "prompt_strategy": self._prompt_strategy,
        })


def build_simple_rag(
    *,
    index: Any,
    llm: Any,
    prompt_strategy: str = "zero_shot",
    retrieval_config: RetrievalConfig | None = None,
    retrieve_fn: Any | None = None,
) -> WorkflowRunner:
    """Factory function matching the registry interface."""
    wf = SimpleRAGWorkflow(
        index=index,
        llm=llm,
        prompt_strategy=prompt_strategy,
        retrieval_config=retrieval_config,
        retrieve_fn=retrieve_fn,
        timeout=120,
    )
    return WorkflowRunner(wf)
