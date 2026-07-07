"""
Export rated traces from MLflow to JSONL (migrated from Phoenix).

Fetches traces in the MLflow experiment that carry a ``user_rating`` feedback
assessment (written by the Chainlit 👍/👎 or a CLI), and serialises them as a
reproducibility artifact for the labeling / bootstrap loop.

Usage::

    python3 -m harness.export_traces \\
        --min-rating 4 \\
        --output results/trajectory_labels.jsonl

    # Or call from Python:
    from harness.export_traces import export_rated_traces
    records = export_rated_traces(min_rating=4, output_path=Path("out.jsonl"))
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from harness.obs.runs import DEFAULT_EXPERIMENT

log = logging.getLogger(__name__)


def _rating_value(assessment: Any) -> float | None:
    """Map a ``user_rating`` feedback value to a 1–5 scale.

    The Chainlit app logs a bool (👍=True / 👎=False); a CLI may log a 0–1 score or
    a 1–5 rating. Normalise all of them to 1–5.
    """
    fb = getattr(assessment, "feedback", None)
    val = getattr(fb, "value", None) if fb is not None else None
    if isinstance(val, bool):
        return 5.0 if val else 1.0
    if isinstance(val, (int, float)):
        v = float(val)
        return v * 5.0 if 0.0 <= v <= 1.0 else v
    return None


def _span_io(spans: list[Any]) -> tuple[str, str, dict]:
    """Best-effort ``(question, answer, ema.* attrs)`` from a trace's spans."""
    question = answer = ""
    ema: dict = {}
    for sp in spans or []:
        attrs = dict(getattr(sp, "attributes", {}) or {})
        for key, value in attrs.items():
            if key.startswith("ema."):
                ema[key] = value
        inp = getattr(sp, "inputs", None)
        out = getattr(sp, "outputs", None)
        if not question and isinstance(inp, dict):
            question = str(inp.get("question") or inp.get("query") or "") or question
        if not answer and isinstance(out, dict):
            answer = str(out.get("answer_text") or out.get("answer") or "") or answer
    return question, answer, ema


def export_rated_traces(
    min_rating: float = 1.0,
    output_path: Path | str | None = None,
    *,
    experiment: str = DEFAULT_EXPERIMENT,
    tracking_uri: str | None = None,
    max_results: int = 500,
) -> list[dict]:
    """Fetch traces carrying a ``user_rating`` assessment and return record dicts.

    Each record::

        {
            "run_id":        str,          # ema.run.id / assessment metadata
            "trace_id":      str,
            "question":      str,
            "answer":        str,
            "rating":        float,        # 1–5 (normalised)
            "step_ratings":  list[dict],   # any "step_quality" assessments
            "index_profile": str,
            "strategy":      str,
        }

    Records below *min_rating* are excluded.
    """
    import mlflow

    from harness.obs import setup_mlflow

    if not setup_mlflow(experiment, tracking_uri=tracking_uri):
        log.warning("mlflow unavailable — nothing to export")
        return []
    exp = mlflow.get_experiment_by_name(experiment)
    if exp is None:
        log.info("experiment %r not found", experiment)
        return []

    traces = mlflow.search_traces(
        experiment_ids=[exp.experiment_id],
        max_results=max_results,
        return_type="list",
    )

    records: list[dict] = []
    for tr in traces:
        assessments = tr.info.assessments or []
        rating_a = next((a for a in assessments if a.name == "user_rating"), None)
        if rating_a is None:
            continue
        rating = _rating_value(rating_a)
        if rating is None or rating < min_rating:
            continue

        spans = tr.data.spans if tr.data else []
        question, answer, ema = _span_io(spans)
        meta = getattr(rating_a, "metadata", None) or {}
        run_id = (
            (meta.get("run_id") if isinstance(meta, dict) else None)
            or ema.get("ema.run.id")
            or tr.info.trace_id
        )
        step_ratings = [
            {
                "name": a.name,
                "label": getattr(getattr(a, "feedback", None), "value", None),
                "metadata": getattr(a, "metadata", None),
            }
            for a in assessments
            if a.name == "step_quality"
        ]
        # Per-citation SME verdicts (log_citation_feedback): the re-ranking signal.
        citation_ratings = [
            {
                "name": a.name,
                "verdict": getattr(getattr(a, "feedback", None), "value", None),
                "rationale": getattr(a, "rationale", None),
                "metadata": getattr(a, "metadata", None),
            }
            for a in assessments
            if a.name.startswith("citation_")
        ]
        records.append(
            {
                "run_id": run_id,
                "trace_id": tr.info.trace_id,
                "question": question,
                "answer": answer,
                "rating": rating,
                "step_ratings": step_ratings,
                "citation_ratings": citation_ratings,
                "index_profile": ema.get("ema.index.profile", ""),
                "strategy": ema.get("ema.orchestration.strategy", ""),
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


def _main() -> None:
    parser = argparse.ArgumentParser(description="Export rated traces from MLflow to JSONL")
    parser.add_argument("--min-rating", type=float, default=1.0)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--experiment", default=DEFAULT_EXPERIMENT)
    parser.add_argument("--tracking-uri", default=None, help="defaults to MLFLOW_TRACKING_URI / ./mlruns")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    records = export_rated_traces(
        min_rating=args.min_rating,
        output_path=args.output,
        experiment=args.experiment,
        tracking_uri=args.tracking_uri,
    )
    for rec in records:
        if not args.output:
            print(json.dumps(rec, ensure_ascii=False))
    print(f"\n{len(records)} record(s) exported.", file=sys.stderr)


if __name__ == "__main__":
    _main()
