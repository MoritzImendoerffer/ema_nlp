"""
Workflow registry — factory for all EMA RAG strategies.

Adding a new strategy requires only:
1. Implementing the workflow (returns WorkflowRunner or compatible object)
2. Adding a builder to WORKFLOW_REGISTRY

Adding a new prompt variant requires only:
1. Adding the prompt file under harness/prompts/
2. Adding an entry to _PROMPT_FILES in harness/workflows/utils.py
3. Setting orchestration.prompt_strategy: <name> in the YAML config

Strategy inventory::

    simple_rag     retrieve → generate (prompt variant from orchestration.prompt_strategy)
    react          ReAct native — hand-written loop, one @step per action (Phoenix spans)
    crag           retrieve → grade ⇄ rewrite → generate
    summarize_rag  retrieve → summarize → generate
    crag_summarize CRAG loop → summarize → generate
    crag_review    CRAG loop → generate → review
    react_review   react (native) → review (score only; no revision)

Usage::

    from harness.workflows.registry import get_workflow, list_workflows
    from harness.llms import get_llm
    from harness.indexing import load_index_profile
    from harness.indexing.property_graph import open_index
    from harness.indexing.registry import build_retriever

    profile   = load_index_profile()              # EMA_INDEX_PROFILE -> neo4j_hier
    retriever = build_retriever(profile, open_index(profile))
    llm       = get_llm("frontier")

    runner = get_workflow("crag_review", retriever=retriever, llm=llm)
    result = runner.invoke({"question": "What is the AI for NDMA?"})

    # With explicit prompt strategy:
    runner = get_workflow("simple_rag", retriever=retriever, llm=llm, prompt_strategy="cot_self")

    print(list_workflows())

CLI::

    python -m harness.workflows.registry --list
"""

from __future__ import annotations

import sys
from typing import Any

# Builder signature: (retriever, llm, **kwargs) → WorkflowRunner-compatible object
WorkflowBuilder = Any


# ---------------------------------------------------------------------------
# Builder functions
# ---------------------------------------------------------------------------

def _build_simple_rag(retriever: Any, llm: Any, **kw: Any) -> Any:
    from harness.workflows.simple_rag import build_simple_rag
    return build_simple_rag(retriever=retriever, llm=llm, **kw)


def _build_react(retriever: Any, llm: Any, **kw: Any) -> Any:
    from harness.workflows.react_native import build_react_native
    return build_react_native(retriever=retriever, llm=llm, **kw)


def _build_crag(retriever: Any, llm: Any, **kw: Any) -> Any:
    from harness.workflows.crag import build_crag
    return build_crag(retriever=retriever, llm=llm, **kw)


def _build_summarize_rag(retriever: Any, llm: Any, **kw: Any) -> Any:
    from harness.workflows.summarize_rag import build_summarize_rag
    return build_summarize_rag(retriever=retriever, llm=llm, **kw)


def _build_crag_summarize(retriever: Any, llm: Any, **kw: Any) -> Any:
    from harness.workflows.composites import build_crag_summarize
    return build_crag_summarize(retriever=retriever, llm=llm, **kw)


def _build_crag_review(retriever: Any, llm: Any, **kw: Any) -> Any:
    from harness.workflows.composites import build_crag_review
    return build_crag_review(retriever=retriever, llm=llm, **kw)


def _build_react_review(retriever: Any, llm: Any, **kw: Any) -> Any:
    from harness.workflows.composites import build_react_review
    return build_react_review(retriever=retriever, llm=llm, **kw)


def _build_agent(retriever: Any, llm: Any, **kw: Any) -> Any:
    # Agentic FunctionAgent exposed as a workflow strategy (additive). The adapter maps
    # its structured RegulatoryAnswer to the {"answer_text", "docs"} runner contract.
    from harness.agents.workflow_adapter import build_agent_workflow
    return build_agent_workflow(retriever, llm, **kw)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

WORKFLOW_REGISTRY: dict[str, WorkflowBuilder] = {
    "simple_rag":    _build_simple_rag,
    "react":         _build_react,        # native per-step workflow (Phoenix spans)
    "crag":          _build_crag,
    "summarize_rag": _build_summarize_rag,
    "crag_summarize": _build_crag_summarize,
    "crag_review":   _build_crag_review,
    "react_review":  _build_react_review,
    "agent":         _build_agent,        # agentic FunctionAgent (structured RegulatoryAnswer)
}


def get_workflow(
    name: str,
    *,
    retriever: Any,
    llm: Any | None = None,
    prompt_strategy: str | None = None,
    **kwargs: Any,
) -> Any:
    """
    Instantiate and return the named workflow runner.

    Each returned object exposes:
        runner.invoke({"question": str}) → dict
        runner.ainvoke({"question": str}) → coroutine → dict

    Args:
        name:             Strategy name (key in WORKFLOW_REGISTRY).
        retriever:        LlamaIndex BaseRetriever (e.g. HierarchicalPGRetriever)
                          built via harness.indexing.registry.build_retriever().
        llm:              Pre-built LlamaIndex LLM; auto-built from 'agent' role if None.
        prompt_strategy:  Prompt variant ("zero_shot" | "few_shot" | "cot_self").
                          Passed to builders that support it (simple_rag, crag, etc.).
        **kwargs:         Passed to the builder.

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

    if prompt_strategy is not None:
        kwargs.setdefault("prompt_strategy", prompt_strategy)

    return WORKFLOW_REGISTRY[name](retriever, llm, **kwargs)


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
