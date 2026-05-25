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
    from harness.embed import build_index

    index = build_index(corpus_path, index_dir)
    llm   = get_llm("frontier")

    runner = get_workflow("crag_review", index=index, llm=llm)
    result = runner.invoke({"question": "What is the AI for NDMA?"})

    # With explicit prompt strategy:
    runner = get_workflow("simple_rag", index=index, llm=llm, prompt_strategy="cot_self")

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

def _build_simple_rag(index: Any, llm: Any, **kw: Any) -> Any:
    from harness.workflows.simple_rag import build_simple_rag
    return build_simple_rag(index=index, llm=llm, **kw)


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
    "simple_rag":    _build_simple_rag,
    "react":         _build_react,        # native per-step workflow (Phoenix spans)
    "crag":          _build_crag,
    "summarize_rag": _build_summarize_rag,
    "crag_summarize": _build_crag_summarize,
    "crag_review":   _build_crag_review,
    "react_review":  _build_react_review,
}


def get_workflow(
    name: str,
    *,
    index: Any,
    llm: Any | None = None,
    retrieval_config: RetrievalConfig | None = None,
    prompt_strategy: str | None = None,
    retrieve_fn: Any | None = None,
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
        prompt_strategy:  Prompt variant ("zero_shot" | "few_shot" | "cot_self").
                          Passed to builders that support it (simple_rag, crag, etc.).
        retrieve_fn:      Pre-built retrieval callable from build_retrieve_fn().
                          When provided, workflows use it instead of building one from
                          retrieval_config alone.  The callable must have a
                          .ablation_config attribute for span stamping.
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

    if retrieval_config is not None:
        kwargs.setdefault("retrieval_config", retrieval_config)

    if prompt_strategy is not None:
        kwargs.setdefault("prompt_strategy", prompt_strategy)

    if retrieve_fn is not None:
        kwargs.setdefault("retrieve_fn", retrieve_fn)

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
