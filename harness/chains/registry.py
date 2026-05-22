"""
Chain registry — factory for all registered EMA RAG strategies (LSMT-010).

Adding a new strategy requires only:
1. Implementing the chain/agent (returns an object with .invoke({"question": str}))
2. Adding a ChainBuilder function to CHAIN_REGISTRY

Strategy inventory
──────────────────
Existing (unchanged — LCEL or standalone LangGraph):
  simple_rag_zero   retrieve → generate (zero-shot)
  simple_rag_few    retrieve → generate (few-shot SME examples)
  simple_rag_cot    retrieve → generate (chain-of-thought)
  react             ReAct tool-calling agent (4 tools)
  crag              retrieve → grade ⇄ rewrite → generate

New (build_pipeline factory, LG-004/005):
  summarize_rag     retrieve → summarize → generate
  crag_summarize    retrieve → grade ⇄ rewrite → summarize → generate
  crag_review       retrieve → grade ⇄ rewrite → generate → review ⇄ revise
  react_review      react subgraph → review (score only; no revision loop)

Usage::

    from harness.chains.registry import get_chain, list_chains
    from harness.chains.retriever import EMARetriever
    from harness.chains.llms import get_langchain_llm

    retriever = EMARetriever(index=index, mode="hybrid", k=10)
    llm = get_langchain_llm("frontier")

    chain = get_chain("crag_review", tier_id="frontier", retriever=retriever, llm=llm)
    result = chain.invoke({"question": "What is the AI for NDMA?"})

    print(list_chains())

CLI::

    python3 -m harness.chains.registry --list
"""

from __future__ import annotations

import sys
from typing import Any, Callable

from harness.chains.retriever import EMARetriever

# Builder signature: (retriever, llm, **kwargs) → Runnable-like object
ChainBuilder = Callable[..., Any]


# ---------------------------------------------------------------------------
# Existing LCEL / standalone builders (unchanged)
# ---------------------------------------------------------------------------

def _build_simple_rag_zero(retriever: EMARetriever, llm: Any, **_: Any) -> Any:
    from harness.chains.simple_rag import build_rag_chain
    return build_rag_chain("zero_shot", retriever=retriever, llm=llm)


def _build_simple_rag_few(retriever: EMARetriever, llm: Any, **_: Any) -> Any:
    from harness.chains.simple_rag import build_rag_chain
    return build_rag_chain("few_shot", retriever=retriever, llm=llm)


def _build_simple_rag_cot(retriever: EMARetriever, llm: Any, **_: Any) -> Any:
    from harness.chains.simple_rag import build_rag_chain
    return build_rag_chain("cot_self", retriever=retriever, llm=llm)


def _build_react(retriever: EMARetriever, llm: Any, **kwargs: Any) -> Any:
    from harness.chains.agents.react import build_react_agent
    return build_react_agent(retriever=retriever, llm=llm, **kwargs)


def _build_crag(retriever: EMARetriever, llm: Any, **kwargs: Any) -> Any:
    from harness.chains.agents.crag import build_crag
    return build_crag(retriever=retriever, llm=llm, **kwargs)


# ---------------------------------------------------------------------------
# New pipeline-factory builders (LG-004/005)
# ---------------------------------------------------------------------------

def _build_summarize_rag(retriever: EMARetriever, llm: Any, **_: Any) -> Any:
    from harness.chains.pipeline import PipelineConfig, build_pipeline
    return build_pipeline(
        PipelineConfig(use_summarization=True),
        retriever=retriever,
        llm=llm,
    )


def _build_crag_summarize(retriever: EMARetriever, llm: Any, **_: Any) -> Any:
    from harness.chains.pipeline import PipelineConfig, build_pipeline
    return build_pipeline(
        PipelineConfig(use_grade=True, use_summarization=True),
        retriever=retriever,
        llm=llm,
    )


def _build_crag_review(retriever: EMARetriever, llm: Any, **_: Any) -> Any:
    from harness.chains.pipeline import PipelineConfig, build_pipeline
    return build_pipeline(
        PipelineConfig(use_grade=True, use_review=True, max_review_cycles=1),
        retriever=retriever,
        llm=llm,
    )


def _build_react_review(retriever: EMARetriever, llm: Any, **kwargs: Any) -> Any:
    """ReAct agent followed by a single faithfulness review (no revision loop)."""
    from harness.chains.agents.react import build_react_agent
    from harness.chains.nodes.review import build_review_node
    from harness.chains.pipeline_state import PipelineState, make_initial_state
    from langgraph.graph import END, StateGraph

    react_agent = build_react_agent(retriever=retriever, llm=llm)
    review_fn = build_review_node(llm, threshold=kwargs.get("review_threshold", 0.6))

    def _react_node(state: PipelineState) -> dict:
        result = react_agent.invoke({"question": state["question"]})
        return {
            "answer_text": result["answer_text"],
            "cited_qa_ids": result["cited_qa_ids"],
            "trajectory": result["trajectory"],
            "docs": result["docs"],
        }

    graph = StateGraph(PipelineState)
    graph.add_node("react", _react_node)
    graph.add_node("review", review_fn)
    graph.set_entry_point("react")
    graph.add_edge("react", "review")
    graph.add_edge("review", END)  # score only — no revision loop for react_review
    compiled = graph.compile()

    class _ReactReviewWrapper:
        def invoke(self, inputs: dict, **kw: Any) -> dict:
            q = inputs.get("question", "")
            state = compiled.invoke(make_initial_state(q), **kw)
            return {
                "answer_text": state.get("answer_text", "No answer generated."),
                "cited_qa_ids": state.get("cited_qa_ids", []),
                "trajectory": state.get("trajectory", []),
                "docs": state.get("docs", []),
                "prompt_strategy": "react_review",
                "review_score": state.get("review_score", 0.0),
                "review_feedback": state.get("review_feedback", ""),
            }

        async def ainvoke(self, inputs: dict, **kw: Any) -> dict:
            q = inputs.get("question", "")
            state = await compiled.ainvoke(make_initial_state(q), **kw)
            return {
                "answer_text": state.get("answer_text", "No answer generated."),
                "cited_qa_ids": state.get("cited_qa_ids", []),
                "trajectory": state.get("trajectory", []),
                "docs": state.get("docs", []),
                "prompt_strategy": "react_review",
                "review_score": state.get("review_score", 0.0),
                "review_feedback": state.get("review_feedback", ""),
            }

        def __call__(self, inputs: dict) -> dict:
            return self.invoke(inputs)

    return _ReactReviewWrapper()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

CHAIN_REGISTRY: dict[str, ChainBuilder] = {
    # Existing strategies (additive approach — unchanged implementations)
    "simple_rag_zero":  _build_simple_rag_zero,
    "simple_rag_few":   _build_simple_rag_few,
    "simple_rag_cot":   _build_simple_rag_cot,
    "react":            _build_react,
    "crag":             _build_crag,
    # New pipeline-factory strategies
    "summarize_rag":    _build_summarize_rag,
    "crag_summarize":   _build_crag_summarize,
    "crag_review":      _build_crag_review,
    "react_review":     _build_react_review,
}


def get_chain(
    name: str,
    *,
    tier_id: str = "mid",
    retriever: EMARetriever,
    llm: Any | None = None,
    **kwargs: Any,
) -> Any:
    """
    Instantiate and return the named chain/agent.

    Args:
        name:      Strategy name (one of CHAIN_REGISTRY keys).
        tier_id:   Model tier if *llm* is not supplied.
        retriever: EMARetriever instance.
        llm:       Pre-built LangChain ChatModel; auto-built from tier_id if None.
        **kwargs:  Passed to the builder (e.g. strategy="cot_self" for crag).

    Raises:
        ValueError: If *name* is not in CHAIN_REGISTRY.
    """
    if name not in CHAIN_REGISTRY:
        available = ", ".join(sorted(CHAIN_REGISTRY))
        raise ValueError(
            f"Unknown chain {name!r}. Available strategies: {available}"
        )

    if llm is None:
        from harness.chains.llms import get_langchain_llm
        llm = get_langchain_llm(tier_id)  # type: ignore[arg-type]

    return CHAIN_REGISTRY[name](retriever, llm, **kwargs)


def list_chains() -> list[str]:
    """Return the list of registered chain names (sorted)."""
    return sorted(CHAIN_REGISTRY)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="List registered EMA RAG chain strategies")
    parser.add_argument("--list", action="store_true", help="Print all registered chain names")
    args = parser.parse_args()
    if args.list or len(sys.argv) == 1:
        for name in list_chains():
            print(name)
