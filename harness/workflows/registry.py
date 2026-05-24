"""
Workflow registry — factory for all EMA RAG strategies.

Adding a new strategy requires only:
1. Implementing the workflow (returns WorkflowRunner or compatible object)
2. Adding a builder to WORKFLOW_REGISTRY

Strategy inventory::

    simple_rag_zero    retrieve → generate (zero-shot)
    simple_rag_few     retrieve → generate (few-shot SME examples)
    simple_rag_cot     retrieve → generate (chain-of-thought)
    react              ReAct native — hand-written loop, one @step per action (Phoenix spans)
    crag               retrieve → grade ⇄ rewrite → generate
    summarize_rag      retrieve → summarize → generate
    crag_summarize     CRAG loop → summarize → generate
    crag_review        CRAG loop → generate → review
    react_review       react (native) → review (score only; no revision)

Usage::

    from harness.workflows.registry import get_workflow, list_workflows
    from harness.llms import get_llm
    from harness.embed import build_index

    index = build_index(corpus_path, index_dir)
    llm   = get_llm("frontier")

    runner = get_workflow("crag_review", index=index, llm=llm)
    result = runner.invoke({"question": "What is the AI for NDMA?"})

    print(list_workflows())

CLI::

    python -m harness.workflows.registry --list
"""

from __future__ import annotations

import sys
from typing import Any

from harness.retrieve import RetrievalConfig

# Builder signature: (index, llm, **kwargs) → WorkflowRunner-compatible object
WorkflowBuilder = Any


# ---------------------------------------------------------------------------
# Builder functions
# ---------------------------------------------------------------------------

def _build_simple_rag_zero(index: Any, llm: Any, **kw: Any) -> Any:
    from harness.workflows.simple_rag import build_simple_rag
    return build_simple_rag("zero_shot", index=index, llm=llm, **kw)


def _build_simple_rag_few(index: Any, llm: Any, **kw: Any) -> Any:
    from harness.workflows.simple_rag import build_simple_rag
    return build_simple_rag("few_shot", index=index, llm=llm, **kw)


def _build_simple_rag_cot(index: Any, llm: Any, **kw: Any) -> Any:
    from harness.workflows.simple_rag import build_simple_rag
    return build_simple_rag("cot_self", index=index, llm=llm, **kw)


def _build_react(index: Any, llm: Any, **kw: Any) -> Any:
    from harness.workflows.react_native import build_react_native
    return build_react_native(index=index, llm=llm, **kw)


def _build_crag(index: Any, llm: Any, **kw: Any) -> Any:
    from harness.workflows.crag import build_crag
    return build_crag(index=index, llm=llm, **kw)


def _build_summarize_rag(index: Any, llm: Any, **kw: Any) -> Any:
    from harness.workflows.summarize_rag import build_summarize_rag
    return build_summarize_rag(index=index, llm=llm, **kw)


def _build_crag_summarize(index: Any, llm: Any, **kw: Any) -> Any:
    from harness.workflows.composites import build_crag_summarize
    return build_crag_summarize(index=index, llm=llm, **kw)


def _build_crag_review(index: Any, llm: Any, **kw: Any) -> Any:
    from harness.workflows.composites import build_crag_review
    return build_crag_review(index=index, llm=llm, **kw)


def _build_react_review(index: Any, llm: Any, **kw: Any) -> Any:
    from harness.workflows.composites import build_react_review
    return build_react_review(index=index, llm=llm, **kw)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

WORKFLOW_REGISTRY: dict[str, WorkflowBuilder] = {
    "simple_rag_zero":  _build_simple_rag_zero,
    "simple_rag_few":   _build_simple_rag_few,
    "simple_rag_cot":   _build_simple_rag_cot,
    "react":            _build_react,           # native per-step workflow (Phoenix spans)
    "crag":             _build_crag,
    "summarize_rag":    _build_summarize_rag,
    "crag_summarize":   _build_crag_summarize,
    "crag_review":      _build_crag_review,
    "react_review":     _build_react_review,
}


def get_workflow(
    name: str,
    *,
    index: Any,
    llm: Any | None = None,
    retrieval_config: RetrievalConfig | None = None,
    **kwargs: Any,
) -> Any:
    """
    Instantiate and return the named workflow runner.

    Each returned object exposes:
        runner.invoke({"question": str}) → dict
        runner.ainvoke({"question": str}) → coroutine → dict

    Args:
        name:             Strategy name (key in WORKFLOW_REGISTRY).
        index:            LlamaIndex VectorStoreIndex.
        llm:              Pre-built LlamaIndex LLM; auto-built from 'agent' role if None.
        retrieval_config: Override retrieval settings.
        **kwargs:         Passed to the builder (e.g. strategy="cot_self" for CRAG).

    Raises:
        ValueError: If name is not in WORKFLOW_REGISTRY.
    """
    if name not in WORKFLOW_REGISTRY:
        available = ", ".join(sorted(WORKFLOW_REGISTRY))
        raise ValueError(
            f"Unknown workflow {name!r}. Available strategies: {available}"
        )

    if llm is None:
        from harness.llms import get_llm
        llm = get_llm("agent")

    if retrieval_config is not None:
        kwargs.setdefault("retrieval_config", retrieval_config)

    return WORKFLOW_REGISTRY[name](index, llm, **kwargs)


def list_workflows() -> list[str]:
    """Return the sorted list of registered workflow strategy names."""
    return sorted(WORKFLOW_REGISTRY)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="List registered EMA RAG workflow strategies")
    parser.add_argument("--list", action="store_true", help="Print all strategy names")
    args = parser.parse_args()
    if args.list or len(sys.argv) == 1:
        for name in list_workflows():
            print(name)
