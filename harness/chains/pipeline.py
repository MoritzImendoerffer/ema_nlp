"""
LangGraph pipeline factory for composable RAG strategies (LG-004).

build_pipeline() assembles a PipelineState StateGraph from PipelineConfig flags.
New strategies require only a new PipelineConfig — no new graph code.

Architecture (phases enabled by config flags):

    retrieve
        │
        ├─[use_grade]──→ grade ──→ [insufficient + not maxed] ──→ rewrite ──→ retrieve
        │                │──→ [sufficient or max rewrites]
        │
        ├─[use_summarization]──→ summarize
        │
        ├──→ generate
        │
        └─[use_review]──→ review ──→ [low score + not maxed] ──→ generate
                          │──→ [high score or max reviews]──→ END

The ReAct agent (react, react_review) is architecturally separate (tool-calling loop
vs. fixed pipeline) and is built by _build_react_review() in registry.py.

Usage::

    from harness.chains.pipeline import PipelineConfig, build_pipeline
    from harness.chains.retriever import EMARetriever
    from harness.chains.llms import get_langchain_llm

    cfg = PipelineConfig(use_grade=True, use_summarization=True, k=12)
    pipeline = build_pipeline(cfg, retriever=retriever, llm=llm)
    result = pipeline.invoke({"question": "What is the AI for NDMA?"})

Interactive sessions (app.py) can enable session checkpointing:

    from langgraph.checkpoint.memory import MemorySaver
    pipeline = build_pipeline(cfg, retriever=retriever, llm=llm, checkpointer=MemorySaver())
    result = pipeline.invoke(
        {"question": "..."},
        config={"configurable": {"thread_id": session_id}},
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from langgraph.graph import END, StateGraph

from harness.chains.nodes.generation import build_generation_node
from harness.chains.nodes.retrieval import build_retrieval_node
from harness.chains.pipeline_state import PipelineState, make_initial_state

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class PipelineConfig:
    """
    Configuration for a RAG pipeline built by build_pipeline().

    All fields are plain Python primitives so configs are YAML-serializable and
    can be specified inline in run YAML files under a ``chain.config:`` section.

    Example YAML::

        chain:
          name: build_pipeline
          config:
            use_grade: true
            use_summarization: true
            k: 15
            prompt_strategy: cot_self
    """

    # ── Retrieval ──────────────────────────────────────────────────────────────
    retrieval_strategy: str = "flat"     # "flat" | "recursive" | "hierarchical"
    retrieval_mode: str = "hybrid"       # "dense" | "bm25" | "hybrid"
    k: int = 10

    # ── Pipeline phases ────────────────────────────────────────────────────────
    use_grade: bool = False              # CRAG-style doc sufficiency check + rewrite loop
    use_summarization: bool = False      # condense docs before generation
    use_review: bool = False             # post-generation faithfulness review

    # ── Loop limits ────────────────────────────────────────────────────────────
    max_rewrite_cycles: int = 2          # max query-rewrite attempts (CRAG loop)
    max_review_cycles: int = 1           # max answer-revision attempts (review loop)
                                         # 0 = just score, no revision

    # ── Generation ────────────────────────────────────────────────────────────
    prompt_strategy: str = "zero_shot"   # "zero_shot" | "few_shot" | "cot_self"
    review_threshold: float = 0.6        # review_score >= this → pass (no revision)

    # ── Few-shot injection (RLHF, LG-006) ─────────────────────────────────────
    few_shot_enabled: bool = False       # whether fewshot_context should be injected


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_pipeline(
    config: PipelineConfig,
    *,
    retriever: Any,
    llm: Any,
    checkpointer: Any = None,
    fewshot_context_by_node: dict[str, str] | None = None,
) -> Any:
    """
    Build and return a compiled LangGraph pipeline for the given PipelineConfig.

    Args:
        config:                 PipelineConfig controlling which nodes are active.
        retriever:              EMARetriever (or any .invoke(query) → list[Document]).
        llm:                    LangChain BaseChatModel.
        checkpointer:           Optional LangGraph checkpointer (e.g. MemorySaver()).
                                When provided, pass thread_id in the config kwarg to
                                enable multi-turn session state.
        fewshot_context_by_node: Optional dict mapping node names to few-shot prefix
                                strings.  Supported keys: "generate", "summarize",
                                "grade", "rewrite".

    Returns:
        A compiled wrapper with .invoke({"question": str}) →
        {"answer_text", "docs", "summary", "cited_qa_ids", "prompt_strategy",
         "rewrite_cycles", "review_score", "review_feedback"}
    """
    fewshot = fewshot_context_by_node or {}

    # ── Build node functions ────────────────────────────────────────────────────

    retrieval_fn = build_retrieval_node(retriever)
    generation_fn = _maybe_wrap_with_fewshot(
        build_generation_node(llm, strategy=config.prompt_strategy),
        fewshot.get("generate", ""),
    )

    graph = StateGraph(PipelineState)
    graph.add_node("retrieve", retrieval_fn)
    graph.add_node("generate", generation_fn)

    # ── Grade + rewrite nodes ──────────────────────────────────────────────────
    if config.use_grade:
        from harness.chains.nodes.grade import build_grade_node
        from harness.chains.nodes.rewrite import build_rewrite_node

        grade_fn = _maybe_wrap_with_fewshot(
            build_grade_node(llm), fewshot.get("grade", "")
        )
        rewrite_fn = _maybe_wrap_with_fewshot(
            build_rewrite_node(llm), fewshot.get("rewrite", "")
        )

        graph.add_node("grade", grade_fn)
        graph.add_node("rewrite", rewrite_fn)
        graph.add_edge("retrieve", "grade")

        max_rw = config.max_rewrite_cycles
        _next_after_grade = "summarize" if config.use_summarization else "generate"

        def _route_after_grade(state: PipelineState) -> str:
            cycle = state.get("rewrite_cycle", 0)
            if state.get("grade") == "sufficient" or cycle >= max_rw:
                if cycle >= max_rw and state.get("grade") != "sufficient":
                    log.warning("pipeline: max rewrite cycles (%d) reached; generating anyway", max_rw)
                return _next_after_grade
            return "rewrite"

        graph.add_conditional_edges(
            "grade",
            _route_after_grade,
            {_next_after_grade: _next_after_grade, "rewrite": "rewrite"},
        )
        graph.add_edge("rewrite", "retrieve")

    else:
        _next_after_retrieve = "summarize" if config.use_summarization else "generate"
        graph.add_edge("retrieve", _next_after_retrieve)

    # ── Summarization node ──────────────────────────────────────────────────────
    if config.use_summarization:
        from harness.chains.nodes.summarization import build_summarization_node

        summarize_fn = _maybe_wrap_with_fewshot(
            build_summarization_node(llm), fewshot.get("summarize", "")
        )
        graph.add_node("summarize", summarize_fn)
        graph.add_edge("summarize", "generate")

    # ── Review node ─────────────────────────────────────────────────────────────
    if config.use_review:
        from harness.chains.nodes.review import build_review_node

        review_fn = build_review_node(llm, threshold=config.review_threshold)
        graph.add_node("review", review_fn)
        graph.add_edge("generate", "review")

        threshold = config.review_threshold
        max_rv = config.max_review_cycles

        def _route_after_review(state: PipelineState) -> str:
            score = state.get("review_score", 0.0)
            cycle = state.get("review_cycle", 0)
            if score >= threshold or cycle > max_rv:
                return "end"
            return "generate"

        graph.add_conditional_edges(
            "review",
            _route_after_review,
            {"end": END, "generate": "generate"},
        )
    else:
        graph.add_edge("generate", END)

    # ── Entry point ────────────────────────────────────────────────────────────
    graph.set_entry_point("retrieve")

    compiled = graph.compile(checkpointer=checkpointer)

    # ── Wrapper with clean interface ───────────────────────────────────────────

    class _PipelineWrapper:
        def invoke(self, inputs: dict, **kwargs: Any) -> dict:
            question = inputs.get("question", "")
            few_shot = inputs.get("few_shot_context", "")
            state = compiled.invoke(
                make_initial_state(question, few_shot_context=few_shot),
                **kwargs,
            )
            return _extract_output(state, config)

        async def ainvoke(self, inputs: dict, **kwargs: Any) -> dict:
            question = inputs.get("question", "")
            few_shot = inputs.get("few_shot_context", "")
            state = await compiled.ainvoke(
                make_initial_state(question, few_shot_context=few_shot),
                **kwargs,
            )
            return _extract_output(state, config)

        def __call__(self, inputs: dict) -> dict:
            return self.invoke(inputs)

    return _PipelineWrapper()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_output(state: PipelineState, config: PipelineConfig) -> dict[str, Any]:
    return {
        "answer_text": state.get("answer_text", "No answer generated."),
        "docs": state.get("docs", []),
        "summary": state.get("summary", ""),
        "cited_qa_ids": state.get("cited_qa_ids", []),
        "prompt_strategy": state.get("prompt_strategy", config.prompt_strategy),
        "rewrite_cycles": state.get("rewrite_cycle", 0),
        "review_score": state.get("review_score", 0.0),
        "review_feedback": state.get("review_feedback", ""),
    }


def _maybe_wrap_with_fewshot(node_fn: Any, fewshot: str) -> Any:
    """Wrap a node function to prepend fewshot to state["few_shot_context"]."""
    if not fewshot:
        return node_fn

    def _wrapped(state: PipelineState) -> dict:
        modified = dict(state)
        existing = state.get("few_shot_context", "")
        modified["few_shot_context"] = fewshot + ("\n\n" + existing if existing else "")
        return node_fn(modified)

    return _wrapped
