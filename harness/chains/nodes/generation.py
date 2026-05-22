"""
Generation node for LangGraph pipelines (LG-001).

Wraps the simple_rag prompt chains (zero_shot, few_shot, cot_self) into a
LangGraph-compatible node function.  Context priority:
  1. state["summary"] — if non-empty (set by summarization_node)
  2. state["docs"]    — formatted via format_docs()

Few-shot injection: if state["few_shot_context"] is non-empty, it is prepended
to the system prompt before the LLM call.

Review-triggered revision: if state["review_cycle"] > 0 and state["review_feedback"]
is non-empty, a revision instruction is appended to the context.

Usage::

    from harness.chains.nodes.generation import build_generation_node

    gen_node = build_generation_node(llm, strategy="zero_shot")
    update = gen_node(state)   # returns {"answer_text": ..., "cited_qa_ids": [], "prompt_strategy": ...}
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from harness.chains.pipeline_state import PipelineState
from harness.chains.simple_rag import extract_answer, format_docs, load_system_prompt

log = logging.getLogger(__name__)

_VALID_STRATEGIES = ("zero_shot", "few_shot", "cot_self")


def build_generation_node(
    llm: Any,
    strategy: str = "zero_shot",
) -> Callable[[PipelineState], dict[str, Any]]:
    """
    Build a generation node for the given prompting strategy.

    Args:
        llm:      LangChain BaseChatModel.
        strategy: "zero_shot" | "few_shot" | "cot_self"

    Returns:
        A node function: (state: PipelineState) -> partial PipelineState update.
    """
    if strategy not in _VALID_STRATEGIES:
        raise ValueError(
            f"Unknown generation strategy {strategy!r}. Choose from: {list(_VALID_STRATEGIES)}"
        )

    base_system = load_system_prompt(strategy)

    def generation_node(state: PipelineState) -> dict[str, Any]:
        # Build context: prefer summary if available
        if state.get("summary"):
            context = state["summary"]
        else:
            context = format_docs(state.get("docs", []))

        # Inject few-shot examples if present
        system = base_system
        if state.get("few_shot_context"):
            system = state["few_shot_context"] + "\n\n" + system

        # Append revision instruction when this is a review-triggered regeneration
        if state.get("review_cycle", 0) > 0 and state.get("review_feedback"):
            context = (
                context
                + "\n\n---\n[REVISION INSTRUCTION] "
                + "Your previous answer was judged insufficient: "
                + state["review_feedback"]
                + "\nPlease address this feedback in your revised answer."
            )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system),
            ("human", "{context}\n\n---\n\nQuestion: {question}"),
        ])
        chain = prompt | llm | StrOutputParser()
        raw = chain.invoke({"context": context, "question": state["question"]})
        answer_text = extract_answer(raw, strategy)
        log.debug("generation_node (strategy=%s): %d chars", strategy, len(answer_text))

        return {
            "answer_text": answer_text,
            "cited_qa_ids": [],    # simple RAG does not extract explicit citation IDs
            "prompt_strategy": strategy,
        }

    return generation_node
