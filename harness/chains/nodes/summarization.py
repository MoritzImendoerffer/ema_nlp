"""
Summarization node for LangGraph pipelines (LG-003).

Condenses the retrieved documents into a focused, citation-preserving summary
before the generation node.  This reduces the token count passed to the
generator and helps frontier models concentrate on the most relevant content.

The summarization prompt is loaded from harness/prompts/system_summarize.md.

Usage::

    from harness.chains.nodes.summarization import build_summarization_node

    summarize_node = build_summarization_node(llm)
    update = summarize_node(state)   # returns {"summary": str}
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from harness.chains.pipeline_state import PipelineState
from harness.chains.simple_rag import format_docs

log = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def build_summarization_node(llm: Any) -> Callable[[PipelineState], dict[str, Any]]:
    """
    Build a summarization node that condenses retrieved docs to a focused summary.

    Args:
        llm: LangChain BaseChatModel.

    Returns:
        A node function: (state: PipelineState) -> {"summary": str}
        Returns {"summary": ""} if no docs are available.
    """
    system_prompt = (_PROMPTS_DIR / "system_summarize.md").read_text(encoding="utf-8")

    _prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "QUESTION: {question}\n\nRELEVANT DOCUMENTS:\n{context}"),
    ])
    _chain = _prompt | llm | StrOutputParser()

    def summarization_node(state: PipelineState) -> dict[str, Any]:
        docs = state.get("docs", [])
        if not docs:
            log.debug("summarization_node: no docs — skipping")
            return {"summary": ""}

        context = format_docs(docs)
        summary = _chain.invoke({
            "question": state["question"],
            "context": context,
        }).strip()

        log.debug(
            "summarization_node: %d chars summary from %d docs",
            len(summary),
            len(docs),
        )
        return {"summary": summary}

    return summarization_node
