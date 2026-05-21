"""
Export rated traces from Phoenix to JSONL (TASK-027.9).

Fetches root agent spans that carry a ``user_rating`` annotation,
then serialises them as a reproducibility artifact that can be committed
to git to snapshot a labeling session.

The output schema is compatible with ablations/B_process_rewards/trajectory_labels.jsonl.

Usage::

    python3 -m harness.export_traces \\
        --min-rating 4 \\
        --output ablations/B_process_rewards/trajectory_labels.jsonl

    # Or call from Python:
    from harness.export_traces import export_rated_traces
    records = export_rated_traces(min_rating=4, output_path=Path("out.jsonl"))
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PHOENIX_URL = "http://localhost:6006"
PHOENIX_PROJECT = "default"


def export_rated_traces(
    min_rating: float = 1.0,
    output_path: Path | str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    model: str | None = None,
    retriever: str | None = None,
    phoenix_url: str = PHOENIX_URL,
    project: str = PHOENIX_PROJECT,
) -> list[dict]:
    """
    Fetch annotated root-spans from Phoenix and return as list of record dicts.

    Each record schema::

        {
            "run_id":       str,          # from annotation metadata
            "span_id":      str,          # Phoenix span ID
            "question":     str,
            "answer":       str,
            "cited_qa_ids": list[str],
            "trajectory":   list[dict],   # tool_call steps extracted from child spans
            "rating":       float,        # 1–5
            "step_ratings": list[dict],   # [{step_idx, label}, ...]
            "model":        str,
            "retriever":    str,
        }

    Records below *min_rating* are excluded. If *model* or *retriever* are
    given, only records matching those strings (substring match) are kept.
    """
    from phoenix.client import Client as PhoenixClient

    client = PhoenixClient(base_url=phoenix_url)

    # --- Fetch root spans ---
    kwargs: dict[str, Any] = {
        "project_identifier": project,
        "parent_id": "null",
        "limit": 500,
    }
    if start_time:
        kwargs["start_time"] = start_time
    if end_time:
        kwargs["end_time"] = end_time

    spans = client.spans.get_spans(**kwargs)
    if not spans:
        log.info("No spans found in project '%s'.", project)
        return []

    log.info("Found %d root spans; fetching annotations…", len(spans))

    # --- Collect span_ids ---
    def _span_id(s: Any) -> str:
        ctx = s.get("context") if isinstance(s, dict) else getattr(s, "context", None)
        if ctx is None:
            return ""
        return (ctx.get("span_id") if isinstance(ctx, dict) else getattr(ctx, "span_id", "")) or ""

    span_ids = [sid for s in spans if (sid := _span_id(s))]

    # --- Fetch annotations in bulk ---
    annotations = client.spans.get_span_annotations(
        span_ids=span_ids,
        project_identifier=project,
    )

    anns_by_span: dict[str, list[Any]] = {}
    for ann in annotations:
        sid = ann.get("span_id") if isinstance(ann, dict) else getattr(ann, "span_id", "")
        if sid:
            anns_by_span.setdefault(sid, []).append(ann)

    # --- Build records ---
    records: list[dict] = []
    for span in spans:
        sid = _span_id(span)
        span_anns = anns_by_span.get(sid, [])

        rating_ann = next(
            (a for a in span_anns if (a.get("name") or a.get("annotation_name", "")) == "user_rating"),
            None,
        )
        if rating_ann is None:
            continue

        meta: dict = rating_ann.get("metadata") or {}
        raw_score: float | None = None
        if "raw_score" in meta:
            raw_score = float(meta["raw_score"])
        elif rating_ann.get("score") is not None:
            raw_score = float(rating_ann["score"]) * 5.0

        if raw_score is None or raw_score < min_rating:
            continue

        attrs = (span.get("attributes") if isinstance(span, dict) else getattr(span, "attributes", {})) or {}

        run_id: str = meta.get("run_id") or sid

        # Per-step quality labels
        step_ratings = [
            {
                "step_idx": int((a.get("metadata") or {}).get("step_idx", 0)),
                "label": a.get("label") or "",
                "tool_name": (a.get("metadata") or {}).get("tool_name", ""),
            }
            for a in span_anns
            if (a.get("name") or a.get("annotation_name", "")) == "step_quality"
        ]

        # Attempt to reconstruct trajectory from child spans
        trajectory = _fetch_child_trajectory(client, project, sid)

        # Extract question / answer from span attributes (OpenInference convention)
        question: str = (
            attrs.get("input.value")
            or attrs.get("llm.input_messages.0.message.content")
            or attrs.get("query")
            or ""
        )
        answer: str = attrs.get("output.value") or attrs.get("response") or ""

        # Parse cited_qa_ids from output if stored as JSON list
        cited: list[str] = []
        if attrs.get("cited_qa_ids"):
            try:
                cited = json.loads(attrs["cited_qa_ids"])
            except (json.JSONDecodeError, TypeError):
                pass

        rec_model: str = attrs.get("llm.model_name") or ""
        rec_retriever: str = attrs.get("retriever.mode") or ""

        # Substring filter
        if model and rec_model and model not in rec_model:
            continue
        if retriever and rec_retriever and retriever not in rec_retriever:
            continue

        records.append(
            {
                "run_id": run_id,
                "span_id": sid,
                "question": question,
                "answer": answer,
                "cited_qa_ids": cited,
                "trajectory": trajectory,
                "rating": raw_score,
                "step_ratings": step_ratings,
                "model": rec_model,
                "retriever": rec_retriever,
            }
        )

    log.info("Exported %d rated records (min_rating=%.1f)", len(records), min_rating)

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        log.info("Written to %s", out)

    return records


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fetch_child_trajectory(client: Any, project: str, parent_span_id: str) -> list[dict]:
    """Reconstruct trajectory from TOOL child spans of a root agent span."""
    try:
        child_spans = client.spans.get_spans(
            project_identifier=project,
            parent_id=parent_span_id,
            span_kind="TOOL",
            limit=50,
        )
        steps: list[dict] = []
        for cs in child_spans:
            attrs = (cs.get("attributes") if isinstance(cs, dict) else getattr(cs, "attributes", {})) or {}
            steps.append(
                {
                    "type": "tool_call",
                    "tool_name": attrs.get("tool.name") or attrs.get("name") or "?",
                    "tool_kwargs": attrs.get("input.value") or "",
                    "tool_output": (attrs.get("output.value") or "")[:300],
                }
            )
        return steps
    except Exception as exc:
        log.debug("Could not fetch child spans for parent=%s: %s", parent_span_id, exc)
        return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _main() -> None:
    parser = argparse.ArgumentParser(description="Export rated traces from Phoenix to JSONL")
    parser.add_argument("--min-rating", type=float, default=1.0)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--retriever", default=None)
    parser.add_argument("--phoenix-url", default=PHOENIX_URL)
    parser.add_argument("--project", default=PHOENIX_PROJECT)
    parser.add_argument(
        "--since",
        default=None,
        help="ISO datetime lower bound, e.g. 2026-05-21T00:00:00Z",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    start_time: datetime | None = None
    if args.since:
        start_time = datetime.fromisoformat(args.since.replace("Z", "+00:00"))

    records = export_rated_traces(
        min_rating=args.min_rating,
        output_path=args.output,
        start_time=start_time,
        model=args.model,
        retriever=args.retriever,
        phoenix_url=args.phoenix_url,
        project=args.project,
    )

    for rec in records:
        if not args.output:
            print(json.dumps(rec, ensure_ascii=False))

    print(f"\n{len(records)} record(s) exported.", file=__import__("sys").stderr)


if __name__ == "__main__":
    _main()
