"""Rebuild a retrieval chain (and an ExportBundle) from a recorded MLflow trace.

The runtime path captures ``ChainStep`` events live (harness.tools.events); this
module reconstructs the same shape *after the fact* from the autolog span tree,
so any past trace — including whole ``scripts/run_eval.py`` runs — can be
rendered by ``ChainHtmlExporter`` (see ``scripts/render_trace.py``).

Span contract (verified empirically against mlflow 3.14 + llama_index autolog):

- tool calls are ``span_type == "TOOL"`` spans; ``outputs`` is a dict with
  ``tool_name`` and ``raw_output`` (the exact string returned to the LLM);
  ``inputs`` is ``{"kwargs": {...}}``.
- retriever calls nest under the tool span as ``span_type == "RETRIEVER"``
  spans whose ``outputs`` items are ``{"page_content", "metadata", "id"}`` with
  the full node metadata (doc_id, title, retrieval_origin, linked_from, ...).

Node lists are parsed from ``raw_output`` (the ``format_nodes`` line format is
the source of truth for *final* order after rerank/steering) and enriched with
the richer RETRIEVER-span metadata by source_url. A trace whose tool outputs
predate this format still yields steps — just with fewer node details.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from harness.export.bundle import ExportBundle
from harness.tools.events import ChainStep, NodeRef

log = logging.getLogger(__name__)

# "[1] source=<url> category=qa score=0.900 via=link_expansion" (search.py) and
# "[1] source=<url> score=0.900 via=topic_subgraph" (topic_context.py).
_NODE_LINE = re.compile(r"^\[(\d+)\] source=(\S+)((?: \w+=\S+)*)\s*$")
_KV = re.compile(r"(\w+)=(\S+)")
# A bracketed steering/status note line, e.g. "[routing: ...]" — but never a
# numbered node entry (those start with "[<digits>] ").
_NOTE_LINE = re.compile(r"^\[(?!\d+\] )[^\]]*\]\s*$")


def _span_type(span: Any) -> str:
    return str(getattr(span, "span_type", "") or "")


def _outputs_dict(span: Any) -> dict[str, Any]:
    out = getattr(span, "outputs", None)
    return out if isinstance(out, dict) else {}


def _tool_name(span: Any) -> str:
    name = _outputs_dict(span).get("tool_name")
    if name:
        return str(name)
    attrs = dict(getattr(span, "attributes", {}) or {})
    return str(attrs.get("name") or getattr(span, "name", "") or "tool")


def _tool_args(span: Any) -> dict[str, Any]:
    inp = getattr(span, "inputs", None)
    if isinstance(inp, dict):
        kwargs = inp.get("kwargs")
        if isinstance(kwargs, dict):
            return dict(kwargs)
        return {k: v for k, v in inp.items() if k != "args"}
    return {}


def _raw_output(span: Any) -> str:
    out = _outputs_dict(span)
    raw = out.get("raw_output")
    if isinstance(raw, str):
        return raw
    outputs = getattr(span, "outputs", None)
    return outputs if isinstance(outputs, str) else ""


def _descendant_retriever_meta(span: Any, spans: list[Any]) -> dict[str, dict[str, Any]]:
    """``source_url -> node metadata`` from RETRIEVER spans nested under ``span``."""
    by_id = {getattr(s, "span_id", None): s for s in spans}
    root_id = getattr(span, "span_id", None)

    def _is_descendant(s: Any) -> bool:
        pid = getattr(s, "parent_id", None)
        while pid is not None:
            if pid == root_id:
                return True
            parent = by_id.get(pid)
            pid = getattr(parent, "parent_id", None) if parent is not None else None
        return False

    meta_by_url: dict[str, dict[str, Any]] = {}
    for s in spans:
        if _span_type(s) != "RETRIEVER" or not _is_descendant(s):
            continue
        out = getattr(s, "outputs", None)
        for item in out if isinstance(out, list) else []:
            meta = item.get("metadata") if isinstance(item, dict) else None
            if isinstance(meta, dict) and meta.get("source_url"):
                # First writer wins per URL; later retrieve() duplicates agree.
                meta_by_url.setdefault(str(meta["source_url"]), meta)
    return meta_by_url


def _nodes_from_output(raw: str, meta_by_url: dict[str, dict[str, Any]]) -> list[NodeRef]:
    """Final ordered node list parsed from the tool's returned string."""
    nodes: list[NodeRef] = []
    for line in raw.splitlines():
        m = _NODE_LINE.match(line.strip())
        if not m:
            continue
        url = m.group(2)
        kv = dict(_KV.findall(m.group(3) or ""))
        meta = meta_by_url.get(url, {})
        try:
            score: float | None = float(kv["score"])
        except (KeyError, ValueError):
            score = meta.get("score") if isinstance(meta.get("score"), (int, float)) else None
        nodes.append(
            NodeRef(
                doc_id=str(meta.get("doc_id") or ""),
                chunk_id=str(meta.get("chunk_id") or ""),
                matched_chunk=str(meta.get("matched_chunk") or ""),
                source_url=url,
                title=str(meta.get("title") or ""),
                category=str(kv.get("category") or meta.get("category") or ""),
                doc_type=meta.get("doc_type"),
                score=score,
                retrieval_origin=str(
                    kv.get("via") or meta.get("retrieval_origin") or "vector"
                ),
                linked_from=[str(d) for d in (meta.get("linked_from") or [])],
                topic_hub=str(meta.get("topic_hub") or ""),
            )
        )
    return nodes


def _notes_from_output(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if _NOTE_LINE.match(line.strip())]


def chain_steps_from_trace(trace: Any) -> list[ChainStep]:
    """Ordered :class:`ChainStep` list reconstructed from a trace's TOOL spans."""
    spans = list(getattr(getattr(trace, "data", None), "spans", None) or [])
    tool_spans = sorted(
        (s for s in spans if _span_type(s) == "TOOL"),
        key=lambda s: getattr(s, "start_time_ns", 0) or 0,
    )
    steps: list[ChainStep] = []
    for seq, span in enumerate(tool_spans, 1):
        raw = _raw_output(span)
        start_ns = getattr(span, "start_time_ns", None)
        end_ns = getattr(span, "end_time_ns", None)
        steps.append(
            ChainStep(
                seq=seq,
                tool=_tool_name(span),
                args=_tool_args(span),
                notes=_notes_from_output(raw),
                nodes=_nodes_from_output(raw, _descendant_retriever_meta(span, spans)),
                started_at=(
                    datetime.fromtimestamp(start_ns / 1e9, tz=UTC).isoformat()
                    if isinstance(start_ns, (int, float)) and start_ns
                    else ""
                ),
                duration_ms=(
                    (end_ns - start_ns) / 1e6
                    if isinstance(start_ns, (int, float)) and isinstance(end_ns, (int, float))
                    else None
                ),
                output_chars=len(raw),
                raw_output=raw,
            )
        )
    return steps


def _find_answer(spans: list[Any]) -> tuple[str, Any]:
    """``(question, RegulatoryAnswer)`` from the span the runner recorded them on.

    ``record_answer_on_span`` writes ``{"question"}`` inputs and the full
    ``RegulatoryAnswer.model_dump()`` outputs on the explicit turn span; take the
    earliest span that carries that shape. Falls back to an empty answer.
    """
    from harness.schemas import RegulatoryAnswer

    question = ""
    for span in sorted(spans, key=lambda s: getattr(s, "start_time_ns", 0) or 0):
        inp = getattr(span, "inputs", None)
        if not question and isinstance(inp, dict) and inp.get("question"):
            question = str(inp["question"])
        out = getattr(span, "outputs", None)
        if isinstance(out, dict) and "answer" in out and "citations" in out:
            try:
                return question, RegulatoryAnswer.model_validate(out)
            except Exception:  # tolerate partial/foreign shapes
                continue
    return question, RegulatoryAnswer(answer="")


def _judge_results(trace: Any) -> list[dict[str, Any]]:
    results = []
    for a in getattr(getattr(trace, "info", None), "assessments", None) or []:
        value = getattr(getattr(a, "feedback", None), "value", None)
        results.append(
            {
                "name": getattr(a, "name", "?"),
                "score": value,
                "rationale": getattr(a, "rationale", "") or "",
            }
        )
    return results


def bundle_from_trace(trace: Any) -> ExportBundle:
    """An :class:`ExportBundle` good enough for ``ChainHtmlExporter`` from one trace.

    Honesty note: reference passages come from the citations' own ``quote``
    fields (the full retrieved passages are not stored on the trace), so the
    attribution is quote-based — the chain view does not need more.
    """
    from harness.attribution import build_attribution

    spans = list(getattr(getattr(trace, "data", None), "spans", None) or [])
    question, answer = _find_answer(spans)
    ema_attrs: dict[str, Any] = {}
    for span in spans:
        for key, value in (dict(getattr(span, "attributes", {}) or {})).items():
            if key.startswith("ema."):
                ema_attrs.setdefault(key, value)

    info = getattr(trace, "info", None)
    trace_id = str(getattr(info, "trace_id", "") or getattr(info, "request_id", "") or "")
    ts_ms = getattr(info, "timestamp_ms", None)
    return ExportBundle(
        question=question,
        answer=answer,
        attribution=build_attribution(answer, [c.quote or "" for c in answer.citations]),
        recipe_name=str(ema_attrs.get("ema.recipe", "") or ""),
        resolved_config=ema_attrs,
        judge_results=_judge_results(trace),
        confidence=answer.confidence,
        run_id=str(ema_attrs.get("ema.run.id", "") or ""),
        trace_id=trace_id,
        asked_at=(
            datetime.fromtimestamp(ts_ms / 1000, tz=UTC).isoformat(timespec="seconds")
            if isinstance(ts_ms, (int, float)) and ts_ms
            else ""
        ),
        chain=[s.to_dict() for s in chain_steps_from_trace(trace)],
    )
