"""
Document sufficiency grading node for LangGraph pipelines (LG-002).

Extracted from harness/chains/agents/crag.py.  The grade node asks the LLM
whether the retrieved documents are sufficient to answer the question and
stores "sufficient" or "insufficient" in PipelineState["grade"].

Usage::

    from harness.chains.nodes.grade import build_grade_node

    grade_node = build_grade_node(llm)
    update = grade_node(state)   # returns {"grade": "sufficient" | "insufficient"}
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from harness.chains.pipeline_state import PipelineState
from harness.chains.simple_rag import format_docs

log = logging.getLogger(__name__)

_GRADE_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a relevance grader for EMA regulatory Q&A retrieval. "
        "Your only job is to decide whether the retrieved documents contain "
        "enough information to answer the question.\n\n"
        "Respond with exactly one word: 'sufficient' or 'insufficient'.\n"
        "Do not explain your reasoning.",
    ),
    (
        "human",
        "Question: {question}\n\nRetrieved documents:\n{context}\n\n"
        "Are these documents sufficient to answer the question?",
    ),
])


def build_grade_node(llm: Any) -> Callable[[PipelineState], dict[str, Any]]:
    """
    Build a document-sufficiency grading node.

    Args:
        llm: LangChain BaseChatModel.

    Returns:
        A node function: (state: PipelineState) -> {"grade": "sufficient" | "insufficient"}
    """
    _chain = _GRADE_PROMPT | llm | StrOutputParser()

    def grade_node(state: PipelineState) -> dict[str, Any]:
        context = format_docs(state.get("docs", []))
        raw = _chain.invoke({"question": state["question"], "context": context})
        raw_lower = raw.lower().strip()
        grade = (
            "sufficient"
            if "sufficient" in raw_lower and "insufficient" not in raw_lower
            else "insufficient"
        )
        log.debug("grade_node (rewrite_cycle=%d): %s", state.get("rewrite_cycle", 0), grade)
        return {"grade": grade}

    return grade_node
