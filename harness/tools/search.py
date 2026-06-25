"""``ema_search`` tool — retrieve EMA corpus passages for the agent.

Retriever-agnostic: wraps any LlamaIndex ``BaseRetriever`` (the live
``CustomPGRetriever`` over Neo4j at runtime, or a fake in tests). When a query
``transform`` and/or ``postprocessors`` are supplied, the tool runs the full
config-driven retrieval pipeline (query expansion -> multi-query merge -> rerank)
via ``harness.retrieval.run_retrieval``; otherwise it does a plain retrieve.

The tool returns a formatted *string* to the LLM (its tool contract), so the
retrieved nodes — and their real ``doc_id``/``chunk_id``/``score`` — are otherwise
lost once the agent authors its answer. ``capture_search_nodes`` lets the runner
collect those nodes during a run so the structured answer's citations carry true
node-derived provenance instead of the URL-only citations the LLM emits.
"""

import contextvars
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from llama_index.core.tools import FunctionTool

from harness.tools.registry import register_tool

log = logging.getLogger(__name__)

_SNIPPET_MAX = 400

# Per-run sink for the ``NodeWithScore`` objects ``ema_search`` retrieves. Held in a
# ContextVar so concurrent agent turns are isolated; ``FunctionTool`` copies the
# context into the executor thread for sync tools (``sync_to_async`` ->
# ``copy_context``), so appends to the shared list are visible to the caller.
_NODE_SINK: contextvars.ContextVar[list | None] = contextvars.ContextVar(
    "ema_search_node_sink", default=None
)


@contextmanager
def capture_search_nodes() -> Iterator[list]:
    """Collect the nodes ``ema_search``/``corrective_search`` retrieve within this scope.

    Yields a list that every search-tool call (there may be several in one agent run)
    appends its retrieved ``NodeWithScore`` objects to. **Nested scopes share the
    outermost sink**: if a capture is already active (e.g. the workflow adapter wraps the
    agent run so it can read the evidence, and ``arun_agent`` opens its own capture
    inside), the inner ``with`` reuses the active list rather than shadowing it — so the
    outer capturer sees the same nodes. The first (outermost) scope owns set/reset.
    """
    existing = _NODE_SINK.get()
    if existing is not None:
        yield existing
        return
    sink: list = []
    token = _NODE_SINK.set(sink)
    try:
        yield sink
    finally:
        _NODE_SINK.reset(token)


def format_nodes(nodes: list) -> str:
    """Render retrieved nodes as a numbered, source-tagged context string."""
    if not nodes:
        return "No results found."
    lines: list[str] = []
    for i, node_with_score in enumerate(nodes, 1):
        node = getattr(node_with_score, "node", node_with_score)
        score = getattr(node_with_score, "score", None)
        meta = getattr(node, "metadata", {}) or {}
        text = getattr(node, "text", "") or ""
        source = meta.get("source_url", "?")
        score_str = f"{score:.3f}" if isinstance(score, (int, float)) else "n/a"
        snippet = " ".join(text.split())[:_SNIPPET_MAX]
        lines.append(f"[{i}] source={source} score={score_str}\n{snippet}")
    return "\n\n".join(lines)


@register_tool("ema_search")
def build_ema_search_tool(
    *,
    retriever: Any = None,
    transform: Any = None,
    postprocessors: list | None = None,
    **_: Any,
) -> FunctionTool:
    """Build the ``ema_search`` FunctionTool over a LlamaIndex retriever.

    If ``transform``/``postprocessors`` are given, the config-driven pipeline runs;
    otherwise a plain ``retriever.retrieve`` is used.
    """
    if retriever is None:
        raise ValueError("ema_search tool requires a `retriever` (a LlamaIndex BaseRetriever)")

    def ema_search(query: str) -> str:
        """Search the EMA regulatory corpus; returns relevant passages with sources."""
        if transform is not None or postprocessors:
            from harness.retrieval.pipeline import run_retrieval

            nodes = run_retrieval(
                retriever, query=query, transform=transform, postprocessors=postprocessors or []
            )
        else:
            nodes = retriever.retrieve(query)
        sink = _NODE_SINK.get()
        if sink is not None:
            sink.extend(nodes)
        return format_nodes(nodes)

    return FunctionTool.from_defaults(
        fn=ema_search,
        name="ema_search",
        description=(
            "Search the EMA human-regulatory corpus (hierarchical retrieval over the "
            "Neo4j knowledge graph) and return relevant passages with their source URLs. "
            "Call this before answering any factual question."
        ),
    )
