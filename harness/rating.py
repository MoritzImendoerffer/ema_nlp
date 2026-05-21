"""
CLI rating UI for agent runs (TASK-027.8).

Called after each interactive agent run to collect user feedback.
Never called during benchmark runs (run_eval.py sets non_interactive=True).

Usage::

    from harness.rating import prompt_for_rating
    ans = agent.run(question)
    prompt_for_rating(run_id, question, ans.text, ans.trajectory, cache=cache)
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC
from typing import Any

log = logging.getLogger(__name__)

PHOENIX_URL = "http://localhost:6006"
PHOENIX_PROJECT = "default"


def prompt_for_rating(
    run_id: str,
    question: str,
    answer_text: str,
    trajectory: list[dict],
    *,
    root_span_id: str | None = None,
    step_span_ids: list[str] | None = None,
    cache: Any = None,
    phoenix_url: str = PHOENIX_URL,
    project: str = PHOENIX_PROJECT,
    non_interactive: bool = False,
) -> float | None:
    """
    Prompt the user for a 1-5 rating after an agent run.

    Posts annotation to Phoenix (if reachable) and updates the query cache.
    Always skippable — Enter with no input skips the rating step.

    Args:
        run_id:          Unique ID for this run (stored in query cache).
        question:        The question posed to the agent.
        answer_text:     The agent's final answer.
        trajectory:      List of step dicts from AgentAnswer.trajectory.
        root_span_id:    OTel span_id of the root agent span (optional; heuristic fallback used if absent).
        step_span_ids:   OTel span_ids for individual trajectory steps (optional).
        cache:           QueryCache instance to sync the rating into.
        phoenix_url:     Base URL of the Phoenix server.
        project:         Phoenix project identifier.
        non_interactive: If True, skip the prompt entirely (used by run_eval.py).

    Returns:
        The rating (1.0–5.0) or None if skipped.
    """
    if non_interactive:
        return None

    # --- Overall rating ---
    print("\nRate this response (1-5, Enter to skip): ", end="", flush=True)
    raw = sys.stdin.readline().strip()
    if not raw:
        return None

    try:
        rating = float(raw)
    except ValueError:
        print("  Invalid input — skipping rating.")
        return None

    if not 1.0 <= rating <= 5.0:
        print("  Rating must be between 1 and 5 — skipping.")
        return None

    # --- Optional explanation ---
    print("Note (Enter to skip): ", end="", flush=True)
    note = sys.stdin.readline().strip() or None

    # --- Optional per-step labels ---
    step_labels: list[dict] = []
    tool_steps = [s for s in trajectory if s.get("type") == "tool_call"]
    if tool_steps:
        print(
            f"Label individual steps? {len(tool_steps)} tool call(s) available [y/N]: ",
            end="",
            flush=True,
        )
        if sys.stdin.readline().strip().lower() == "y":
            label_map = {"g": "good_step", "s": "suboptimal_step", "w": "wrong_step"}
            for i, step in enumerate(tool_steps):
                tool_name = step.get("tool_name", "?")
                kwargs_preview = str(step.get("tool_kwargs", ""))[:60]
                print(
                    f"  Step {i + 1}/{len(tool_steps)}: {tool_name}({kwargs_preview})\n"
                    f"    [g]ood / [s]uboptimal / [w]rong / Enter=skip: ",
                    end="",
                    flush=True,
                )
                lraw = sys.stdin.readline().strip().lower()
                if lraw in label_map:
                    step_labels.append({"step_idx": i, "tool_name": tool_name, "label": label_map[lraw]})

    # --- Post to Phoenix ---
    _post_phoenix_annotation(
        run_id=run_id,
        root_span_id=root_span_id,
        step_span_ids=step_span_ids or [],
        step_labels=step_labels,
        rating=rating,
        note=note,
        phoenix_url=phoenix_url,
        project=project,
    )

    # --- Update cache ---
    if cache is not None:
        cache.update_rating(run_id, rating)
        log.debug("Cache rating updated: run_id=%s → %.1f", run_id, rating)

    note_suffix = f' — "{note}"' if note else ""
    print(f"  Saved rating {rating:.0f}/5{note_suffix}.")
    return rating


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _post_phoenix_annotation(
    run_id: str,
    root_span_id: str | None,
    step_span_ids: list[str],
    step_labels: list[dict],
    rating: float,
    note: str | None,
    phoenix_url: str,
    project: str,
) -> None:
    try:
        from phoenix.client import Client as PhoenixClient

        client = PhoenixClient(base_url=phoenix_url)

        # Resolve span_id if not supplied — use the most recent root span
        if root_span_id is None:
            root_span_id = _find_recent_root_span_id(client, project)

        if root_span_id:
            client.spans.add_span_annotation(
                span_id=root_span_id,
                annotation_name="user_rating",
                annotator_kind="HUMAN",
                score=rating / 5.0,
                label=f"{int(rating)}/5",
                explanation=note,
                metadata={"run_id": run_id, "raw_score": rating},
            )
            log.info("Phoenix annotation posted: run_id=%s span_id=%s rating=%.1f", run_id, root_span_id, rating)
        else:
            log.warning("Phoenix annotation skipped — no span_id found for run_id=%s", run_id)

        # Per-step labels on child spans (best-effort)
        for sl in step_labels:
            idx = sl["step_idx"]
            if idx < len(step_span_ids):
                client.spans.add_span_annotation(
                    span_id=step_span_ids[idx],
                    annotation_name="step_quality",
                    annotator_kind="HUMAN",
                    label=sl["label"],
                    metadata={"run_id": run_id, "step_idx": idx, "tool_name": sl.get("tool_name", "")},
                )

    except Exception as exc:
        log.warning("Phoenix annotation failed (non-fatal): %s", exc)


def _find_recent_root_span_id(client: Any, project: str) -> str | None:
    """Heuristic: return the most recent root span in the last 5 minutes."""
    try:
        from datetime import datetime, timedelta

        spans = client.spans.get_spans(
            project_identifier=project,
            start_time=datetime.now(UTC) - timedelta(minutes=5),
            parent_id="null",
            limit=1,
        )
        if spans:
            ctx = spans[0].get("context") if isinstance(spans[0], dict) else getattr(spans[0], "context", None)
            if ctx:
                return ctx.get("span_id") if isinstance(ctx, dict) else getattr(ctx, "span_id", None)
    except Exception as exc:
        log.debug("Could not look up recent span: %s", exc)
    return None
