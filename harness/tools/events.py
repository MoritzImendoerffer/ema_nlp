"""Chain-event capture — the ordered story of one agent run's retrieval tool calls.

``capture_search_nodes`` (harness.tools.search) collects the *nodes* a run retrieved,
but flattens away *how*: which tool ran, in what order, with which arguments, under
which routing/steering decision. This module records that story as ``ChainStep``
events so the chain-HTML export (harness.export.chain_html) can show how the LLM
context evolved — without changing any tool's contract with the agent.

Same ContextVar idiom as ``_NODE_SINK``: the outermost ``capture_chain_events``
scope owns the sink, nested scopes reuse it, and ``record_tool_event`` is a no-op
when no scope is active — so the tools stay usable outside a capturing runner.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

_EVENT_SINK: contextvars.ContextVar[list[ChainStep] | None] = contextvars.ContextVar(
    "ema_chain_event_sink", default=None
)


@dataclass
class NodeRef:
    """Provenance-only projection of one retrieved ``NodeWithScore``.

    Carries what the chain view needs (identity, source labels, origin, expansion
    seeds) — never the passage text, which lives in the node sink / citations.
    """

    doc_id: str = ""
    chunk_id: str = ""
    matched_chunk: str = ""
    source_url: str = ""
    title: str = ""
    category: str = ""
    doc_type: str | None = None
    score: float | None = None
    retrieval_origin: str = "vector"
    linked_from: list[str] = field(default_factory=list)  # seed doc_ids (link_expansion)
    topic_hub: str = ""
    # Site-tree placement inputs (the chain export's tree view parents docs by
    # breadcrumb + source_type — see harness.indexing.site_tree).
    topic_path: str = ""
    source_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "chunk_id": self.chunk_id,
            "matched_chunk": self.matched_chunk,
            "source_url": self.source_url,
            "title": self.title,
            "category": self.category,
            "doc_type": self.doc_type,
            "score": self.score,
            "retrieval_origin": self.retrieval_origin,
            "linked_from": list(self.linked_from),
            "topic_hub": self.topic_hub,
            "topic_path": self.topic_path,
            "source_type": self.source_type,
        }


@dataclass
class ChainStep:
    """One retrieval-shaped tool call, in run order."""

    seq: int
    tool: str  # ema_search | corrective_search | topic_context
    args: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)  # verbatim [routing:...] / [category filter:...]
    nodes: list[NodeRef] = field(default_factory=list)  # ordered as returned to the LLM
    started_at: str = ""  # ISO timestamp
    duration_ms: float | None = None
    output_chars: int = 0
    raw_output: str = ""  # full tool output; rendered only when export opts in

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "tool": self.tool,
            "args": dict(self.args),
            "notes": list(self.notes),
            "nodes": [n.to_dict() for n in self.nodes],
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
            "output_chars": self.output_chars,
            "raw_output": self.raw_output,
        }


def node_ref_from_nws(nws: Any) -> NodeRef:
    """Project a ``NodeWithScore`` (or bare node) onto a :class:`NodeRef`.

    Reads the provenance meta stamped by ``HierarchicalPGRetriever._node_from_row``
    and ``topic_context._chunk_node`` — tolerant of missing keys (fakes in tests).
    """
    node = getattr(nws, "node", nws)
    meta = getattr(node, "metadata", {}) or {}
    score = getattr(nws, "score", None)
    return NodeRef(
        doc_id=str(meta.get("doc_id") or ""),
        chunk_id=str(meta.get("chunk_id") or getattr(node, "node_id", "") or ""),
        matched_chunk=str(meta.get("matched_chunk") or ""),
        source_url=str(meta.get("source_url") or ""),
        title=str(meta.get("title") or ""),
        category=str(meta.get("category") or ""),
        doc_type=meta.get("doc_type"),
        score=float(score) if isinstance(score, (int, float)) else None,
        retrieval_origin=str(meta.get("retrieval_origin") or "vector"),
        linked_from=[str(d) for d in (meta.get("linked_from") or [])],
        topic_hub=str(meta.get("topic_hub") or ""),
        topic_path=str(meta.get("topic_path") or ""),
        source_type=str(meta.get("source_type") or ""),
    )


@contextmanager
def capture_chain_events() -> Iterator[list[ChainStep]]:
    """Collect the :class:`ChainStep` events recorded within this scope.

    Nested scopes share the outermost sink (same contract as
    ``capture_search_nodes``): the first scope owns set/reset, inner ``with``
    blocks reuse the active list so the outer capturer sees every step.
    """
    existing = _EVENT_SINK.get()
    if existing is not None:
        yield existing
        return
    sink: list[ChainStep] = []
    token = _EVENT_SINK.set(sink)
    try:
        yield sink
    finally:
        _EVENT_SINK.reset(token)


def record_tool_event(
    *,
    tool: str,
    args: dict[str, Any],
    notes: list[str],
    nodes: list,
    output: str = "",
    started_at: str = "",
    duration_ms: float | None = None,
) -> None:
    """Append one :class:`ChainStep` to the active capture scope (no-op outside one).

    ``nodes`` are raw ``NodeWithScore`` objects — projected to :class:`NodeRef`
    here so callers just pass what they sink. ``output`` is the tool's returned
    string; it is kept on the step (a few KB per call) so the chain export can
    show it when ``include_chain_output`` is enabled — rendering, not capture,
    is the gate.
    """
    sink = _EVENT_SINK.get()
    if sink is None:
        return
    sink.append(
        ChainStep(
            seq=len(sink) + 1,
            tool=tool,
            args=dict(args),
            notes=list(notes),
            nodes=[node_ref_from_nws(n) for n in nodes],
            started_at=started_at,
            duration_ms=duration_ms,
            output_chars=len(output),
            raw_output=output,
        )
    )
