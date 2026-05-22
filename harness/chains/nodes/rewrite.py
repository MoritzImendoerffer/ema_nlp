"""
Query rewriting node for LangGraph pipelines (LG-002).

Extracted from harness/chains/agents/crag.py.  The rewrite node asks the LLM
to produce a more specific EMA-terminology query when initial retrieval was
insufficient.  Increments PipelineState["rewrite_cycle"] on each call.

Usage::

    from harness.chains.nodes.rewrite import build_rewrite_node

    rewrite_node = build_rewrite_node(llm)
    update = rewrite_node(state)   # returns {"question": new_query, "rewrite_cycle": n+1}
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from harness.chains.pipeline_state import PipelineState

log = logging.getLogger(__name__)

_REWRITE_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a query rewriter for EMA regulatory document retrieval. "
        "The original query did not retrieve sufficient documents. "
        "Rewrite it to be more specific, using EMA terminology. "
        "Return only the rewritten query, nothing else.",
    ),
    ("human", "Original query: {question}"),
])


def build_rewrite_node(llm: Any) -> Callable[[PipelineState], dict[str, Any]]:
    """
    Build a query-rewriting node.

    Args:
        llm: LangChain BaseChatModel.

    Returns:
        A node function: (state: PipelineState) ->
            {"question": new_query, "rewrite_cycle": cycle + 1}
    """
    _chain = _REWRITE_PROMPT | llm | StrOutputParser()

    def rewrite_node(state: PipelineState) -> dict[str, Any]:
        old_question = state["question"]
        new_question = _chain.invoke({"question": old_question}).strip()
        cycle = state.get("rewrite_cycle", 0) + 1
        log.debug(
            "rewrite_node (cycle %d→%d): %r → %r",
            cycle - 1,
            cycle,
            old_question[:60],
            new_question[:60],
        )
        return {"question": new_question, "rewrite_cycle": cycle}

    return rewrite_node
