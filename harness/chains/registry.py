"""
Chain registry — factory for all registered EMA RAG strategies (LSMT-010).

Adding a new strategy requires only:
1. Implementing the chain/agent (returns an object with .invoke({"question": str}))
2. Adding a ChainBuilder function to CHAIN_REGISTRY

Usage::

    from harness.chains.registry import get_chain, list_chains
    from harness.chains.retriever import EMARetriever
    from harness.chains.llms import get_langchain_llm

    retriever = EMARetriever(index=index, mode="hybrid", k=10)
    llm = get_langchain_llm("frontier")

    chain = get_chain("crag", tier_id="frontier", retriever=retriever, llm=llm)
    result = chain.invoke({"question": "What is the AI for NDMA?"})

    # List available strategies
    print(list_chains())
    # ['simple_rag_zero', 'simple_rag_few', 'simple_rag_cot', 'react', 'crag']

CLI::

    python3 -m harness.chains.registry --list
"""

from __future__ import annotations

import sys
from typing import Any, Callable

from harness.chains.retriever import EMARetriever

# Builder signature: (retriever, llm, **kwargs) → Runnable-like object
ChainBuilder = Callable[..., Any]


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


CHAIN_REGISTRY: dict[str, ChainBuilder] = {
    "simple_rag_zero": _build_simple_rag_zero,
    "simple_rag_few":  _build_simple_rag_few,
    "simple_rag_cot":  _build_simple_rag_cot,
    "react":           _build_react,
    "crag":            _build_crag,
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
