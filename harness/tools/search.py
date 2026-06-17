"""``ema_search`` tool — retrieve EMA corpus passages for the agent.

Retriever-agnostic: wraps any LlamaIndex ``BaseRetriever`` (the live
``CustomPGRetriever`` over Neo4j at runtime, or a fake in tests). When a query
``transform`` and/or ``postprocessors`` are supplied, the tool runs the full
config-driven retrieval pipeline (query expansion -> multi-query merge -> rerank)
via ``harness.retrieval.run_retrieval``; otherwise it does a plain retrieve.
"""

import logging
from typing import Any

from llama_index.core.tools import FunctionTool

from harness.tools.registry import register_tool

log = logging.getLogger(__name__)

_SNIPPET_MAX = 400


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
