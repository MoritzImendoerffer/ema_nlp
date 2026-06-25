"""``corrective_search`` tool — CRAG retrieval-correction as an agent tool.

Runs the deterministic, **bounded** Corrective-RAG loop inside the tool: retrieve →
grade each passage's relevance → if the set doesn't cover the question, rewrite the
query toward the missing facts and retry (up to ``max_cycles``). Returns the
*corrected passages* (plus a short grade note), NOT a final answer — the agent still
authors the answer, so structured output and citations stay in one place.

This is the agent-tool packaging of CRAG: the recipe's system prompt instructs the
agent *when* to call it (e.g. for multi-hop/scoping questions); the loop itself is
code, so its bound and sufficiency rule are deterministic and inspectable. The
grading rubric / parser / sufficiency rule / rewrite prompt are shared with the
legacy ``CRAGWorkflow`` via ``harness.retrieval.corrective`` (no logic fork).
Reference: Yan et al., 2024, "Corrective Retrieval Augmented Generation"
(arXiv:2401.15884).

Like ``ema_search`` it is synchronous and feeds retrieved nodes into the shared
``_NODE_SINK`` so the runner can rebuild node-derived citations.
"""

from __future__ import annotations

import logging
from typing import Any

from llama_index.core.tools import FunctionTool

from harness.retrieval.corrective import (
    MAX_CYCLES,
    grade_messages,
    grade_note,
    is_sufficient,
    parse_grade,
    rewrite_messages,
)
from harness.tools.registry import register_tool
from harness.tools.search import _NODE_SINK, format_nodes

log = logging.getLogger(__name__)


@register_tool("corrective_search")
def build_corrective_search_tool(
    *,
    retriever: Any = None,
    llm: Any = None,
    grader_role: str = "grader",
    max_cycles: int = MAX_CYCLES,
    transform: Any = None,
    postprocessors: list | None = None,
    **_: Any,
) -> FunctionTool:
    """Build the ``corrective_search`` FunctionTool.

    Args:
        retriever:      LlamaIndex ``BaseRetriever`` (required).
        llm:            Explicit grading/rewriting LLM. **Normally ``None`` in production**
                        (the agent does NOT pass its own model here) so the cheap
                        ``grader_role`` from models.yaml is built lazily — CRAG
                        grading/rewriting is intentionally a small, fast model, separate
                        from the agent. Tests inject a fake grader via this param.
        grader_role:    models.yaml role for the grading LLM when ``llm`` is ``None``.
        max_cycles:     Max retrieve→rewrite cycles before accepting best-so-far.
        transform/postprocessors: optional retrieval-pipeline stages (same as
                        ``ema_search``); applied on every (re)retrieval.
    """
    if retriever is None:
        raise ValueError("corrective_search tool requires a `retriever` (a LlamaIndex BaseRetriever)")

    # Resolve the grader lazily (on first call), so building the tool/agent needs no model
    # credentials — only invoking corrective_search does. An injected ``llm`` (tests) wins.
    _grader: dict[str, Any] = {"llm": llm}

    def _get_grader() -> Any:
        if _grader["llm"] is None:
            from harness.llms import get_llm

            _grader["llm"] = get_llm(grader_role)
        return _grader["llm"]

    def _retrieve(q: str) -> list:
        if transform is not None or postprocessors:
            from harness.retrieval.pipeline import run_retrieval

            return run_retrieval(
                retriever, query=q, transform=transform, postprocessors=postprocessors or []
            )
        return retriever.retrieve(q)

    def corrective_search(query: str) -> str:
        """Corrective retrieval: search, grade relevance, and rewrite+retry (bounded)
        when the passages don't fully cover the question. Returns corrected passages."""
        grade_llm = _get_grader()
        q = query
        nodes = _retrieve(q)
        resp = grade_llm.chat(grade_messages(q, format_nodes(nodes)))
        per_doc, missing = parse_grade(resp.message.content or "")

        cycles = 0
        while not is_sufficient(per_doc, missing) and cycles < max_cycles:
            rw = grade_llm.chat(rewrite_messages(q, missing))
            q = (rw.message.content or q).strip()
            cycles += 1
            log.debug("corrective_search: rewrite cycle %d → %r", cycles, q[:80])
            nodes = _retrieve(q)
            resp = grade_llm.chat(grade_messages(q, format_nodes(nodes)))
            per_doc, missing = parse_grade(resp.message.content or "")

        # Feed the corrected nodes into the shared sink so the runner can rebuild
        # real node-derived citations (same mechanism as ema_search).
        sink = _NODE_SINK.get()
        if sink is not None:
            sink.extend(nodes)

        return format_nodes(nodes) + grade_note(cycles, per_doc, missing)

    return FunctionTool.from_defaults(
        fn=corrective_search,
        name="corrective_search",
        description=(
            "Corrective retrieval over the EMA human-regulatory corpus: searches, grades "
            "each passage's relevance, and automatically rewrites the query and retries "
            "(bounded) when the passages do not fully cover the question. Prefer this over "
            "ema_search for multi-hop or scoping questions where a single search may miss "
            "part of the answer. Returns the corrected passages with their source URLs."
        ),
    )
