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
    from harness.indexing import load_index_profile
    from harness.indexing.property_graph import open_index
    from harness.indexing.registry import build_retriever

    profile   = load_index_profile()
    retriever = build_retriever(profile, open_index(profile))
    llm       = get_llm("frontier")
    wf    = WorkflowRunner(SimpleRAGWorkflow(retriever=retriever, llm=llm, prompt_strategy="cot_self"))
    result = wf.invoke({"question": "What is the AI for NDMA?"})
"""

from __future__ import annotations

import logging
from typing import Any

from llama_index.core.workflow import Context, StartEvent, StopEvent, Workflow, step

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

_VALID_STRATEGIES = {"zero_shot", "few_shot", "cot_self"}


class SimpleRAGWorkflow(Workflow):
    """
    Single-step RAG: retrieve → generate.

    Args:
        retriever:        LlamaIndex BaseRetriever (HierarchicalPGRetriever).
        llm:              LlamaIndex LLM (from harness.llms.get_llm).
        prompt_strategy:  "zero_shot" | "few_shot" | "cot_self".
    """

    def __init__(
        self,
        *,
        retriever: Any,
        llm: Any,
        prompt_strategy: str = "zero_shot",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if prompt_strategy not in _VALID_STRATEGIES:
            raise ValueError(f"Unknown prompt_strategy {prompt_strategy!r}. Choose from: {_VALID_STRATEGIES}")
        self._retriever = retriever
        self._llm = llm
        self._prompt_strategy = prompt_strategy
        self._system_prompt = load_system_prompt(prompt_strategy)

    def config_attributes(self) -> dict:
        return {
            "ema.orchestration.strategy": "simple_rag",
            "ema.orchestration.prompt_strategy": self._prompt_strategy,
            **retriever_attributes(self._retriever),
        }

    @step
    async def retrieve_and_generate(self, ctx: Context, ev: StartEvent) -> StopEvent:
        question: str = ev.get("question", "")
        few_shot_context: str = ev.get("few_shot_context", "")

        docs = nodes_from_retrieval(await self._retriever.aretrieve(question))
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
    retriever: Any,
    llm: Any,
    prompt_strategy: str = "zero_shot",
) -> WorkflowRunner:
    """Factory function matching the registry interface."""
    wf = SimpleRAGWorkflow(
        retriever=retriever,
        llm=llm,
        prompt_strategy=prompt_strategy,
        timeout=120,
    )
    return WorkflowRunner(wf)
