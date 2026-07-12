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


def passages_from_nodes(nodes: list) -> list[str]:
    """Full passage texts from captured ``NodeWithScore`` objects (empties dropped).

    The shared extraction for everything that grades faithfulness against the real
    retrieval: the workflow adapter's ``context_passages`` result key and the eval
    ``predict_fn`` both use it, so the inline and offline judges see the same context.
    """
    return [
        text
        for nws in nodes
        if (text := (getattr(getattr(nws, "node", nws), "text", "") or "").strip())
    ]


def format_nodes(nodes: list) -> str:
    """Render retrieved nodes as a numbered, source-tagged context string.

    Each entry is tagged with its source ``category`` (and ``via=link_expansion``
    for link-graph-expanded results) so the agent can *see* the source-type mix
    and steer a follow-up search (``source_category=...``) when it doesn't fit
    the question.
    """
    if not nodes:
        return "No results found."
    from harness.retrieval.steering import node_category

    lines: list[str] = []
    for i, node_with_score in enumerate(nodes, 1):
        node = getattr(node_with_score, "node", node_with_score)
        score = getattr(node_with_score, "score", None)
        meta = getattr(node, "metadata", {}) or {}
        text = getattr(node, "text", "") or ""
        source = meta.get("source_url", "?")
        score_str = f"{score:.3f}" if isinstance(score, (int, float)) else "n/a"
        origin = meta.get("retrieval_origin")
        via = f" via={origin}" if origin and origin != "vector" else ""
        snippet = " ".join(text.split())[:_SNIPPET_MAX]
        lines.append(
            f"[{i}] source={source} category={node_category(node_with_score)} "
            f"score={score_str}{via}\n{snippet}"
        )
    return "\n\n".join(lines)


@register_tool("ema_search")
def build_ema_search_tool(
    *,
    retriever: Any = None,
    transform: Any = None,
    postprocessors: list | None = None,
    router: Any = None,
    **_: Any,
) -> FunctionTool:
    """Build the ``ema_search`` FunctionTool over a LlamaIndex retriever.

    If ``transform``/``postprocessors`` are given, the config-driven pipeline runs;
    otherwise a plain ``retriever.retrieve`` is used.

    Source-category steering (see docs/RETRIEVAL.md), strictly precedence-ordered:

    1. The agent's explicit ``source_category`` argument wins — it becomes a hard
       category filter (via ``retriever.with_categories``).
    2. Otherwise, an optional ``router`` (a ``QueryRouter`` from the recipe's
       ``retrieval.routing`` table) may yield a prior: ``filter`` restricts the
       retrieval; ``prefer`` reorders results with the routed categories first.
    3. Otherwise, plain retrieval.

    Every applied steering step is prepended to the tool output as a bracketed
    note — the agent (and the trace reader) always sees what steered the search.
    A hard filter that yields nothing automatically retries unfiltered (with a
    note) so steering can never silently blank out retrieval.
    """
    if retriever is None:
        raise ValueError("ema_search tool requires a `retriever` (a LlamaIndex BaseRetriever)")

    def _run(active_retriever: Any, query: str) -> list:
        if transform is not None or postprocessors:
            from harness.retrieval.pipeline import run_retrieval

            return run_retrieval(
                active_retriever,
                query=query,
                transform=transform,
                postprocessors=postprocessors or [],
            )
        return active_retriever.retrieve(query)

    def ema_search(query: str, source_category: str = "") -> str:
        """Search the EMA regulatory corpus; returns relevant passages with sources.

        Args:
            query: The search query.
            source_category: Optional comma-separated source categories to
                restrict the search to (see the tool description for the list).
        """
        from harness.retrieval.steering import parse_categories, sort_by_category_priority

        notes: list[str] = []
        categories: list[str] | None = None
        mode = "filter"
        if source_category:
            try:
                categories = parse_categories(source_category) or None
            except ValueError as exc:
                return str(exc)  # agent-visible: names the valid categories
            if categories:
                notes.append(f"[category filter: {', '.join(categories)}]")
        elif router is not None:
            decision = router.route(query)
            if decision is not None:
                categories, mode = list(decision.categories), decision.mode
                notes.append(
                    f"[routing: rule '{decision.rule}' -> {mode} {', '.join(categories)}]"
                )
                log.info("ema_search routed by rule %r (%s %s)", decision.rule, mode, categories)

        active_retriever = retriever
        if categories and mode == "filter":
            if hasattr(retriever, "with_categories"):
                active_retriever = retriever.with_categories(categories)
            else:
                notes.append(
                    "[category filter not supported by this retriever - searching unfiltered]"
                )
                categories = None

        nodes = _run(active_retriever, query)
        if not nodes and active_retriever is not retriever:
            # A hard filter must never blank out retrieval (e.g. category not yet
            # backfilled, or genuinely no such source) — fall back, honestly noted.
            notes.append(
                f"[no results in categor(ies) {', '.join(categories or [])} - retried unfiltered]"
            )
            nodes = _run(retriever, query)
        elif categories and mode == "prefer":
            nodes = sort_by_category_priority(nodes, categories)

        sink = _NODE_SINK.get()
        if sink is not None:
            sink.extend(nodes)
        body = format_nodes(nodes)
        return "\n".join(notes) + ("\n\n" if notes else "") + body

    from harness.retrieval.doc_categories import CATEGORIES

    return FunctionTool.from_defaults(
        fn=ema_search,
        name="ema_search",
        description=(
            "Search the EMA human-regulatory corpus (hierarchical retrieval over the "
            "Neo4j knowledge graph) and return relevant passages with their source URLs "
            "and source category. Call this before answering any factual question. "
            "Optional `source_category` restricts the search to one or more categories "
            f"(comma-separated) out of: {', '.join(CATEGORIES)}. Use it when the "
            "results' categories do not fit the question — e.g. when a question about "
            "general requirements keeps returning product-specific documents."
        ),
    )
