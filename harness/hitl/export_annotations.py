"""
Export Phoenix span annotations to a Nextcloud JSONL file.

Each labelled span becomes one JSON record:

    {
        "trace_id":     str,
        "span_id":      str,
        "span_name":    str,
        "input":        str | null,
        "output":       str | null,
        "labels":       {"annotation_name": "label_value", ...},
        "scores":       {"annotation_name": float, ...},
        "reason":       str | null,
        "annotated_by": str | null,
        "annotated_at": str,   # ISO-8601 UTC
    }

Output path: ~/Nextcloud/Datasets/ema_nlp/annotations/YYYY-MM-DD.jsonl

Phoenix REST API used:
  GET /v1/spans?project_name=default&filter=...  → span list
  GET /v1/span_annotations?span_ids=...          → annotation list

Usage:
    # Export all annotations since a date
    python -m harness.hitl.export_annotations --since 2026-05-20

    # Export only react strategy spans
    python -m harness.hitl.export_annotations --since 2026-05-20 --strategy react

    # Preview without writing
    python -m harness.hitl.export_annotations --since 2026-05-20 --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

log = logging.getLogger(__name__)

_DEFAULT_PHOENIX_URL = "http://localhost:6006"
_DEFAULT_NEXTCLOUD = Path("~/Nextcloud/Datasets/ema_nlp/annotations").expanduser()


def _phoenix_base() -> str:
    return os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", _DEFAULT_PHOENIX_URL).rstrip("/")


def _get_json(url: str, timeout: int = 30) -> Any:
    try:
        with urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as exc:
        raise RuntimeError(f"Phoenix HTTP {exc.code}: {exc.reason} — {url}") from exc
    except URLError as exc:
        raise RuntimeError(
            f"Cannot reach Phoenix at {_phoenix_base()} — is it running? ({exc.reason})"
        ) from exc


def _fetch_annotated_spans(
    since: str,
    strategy: str | None,
    project_name: str = "default",
) -> list[dict]:
    """Return spans that have at least one annotation, created after `since` (ISO date)."""
    params: dict[str, str] = {
        "project_name": project_name,
        "start_time": since,
    }
    if strategy:
        # Workflow name is stored as an attribute on root spans
        params["filter"] = f'attributes["workflow_name"] == "{strategy}"'

    url = f"{_phoenix_base()}/v1/spans?{urlencode(params)}"
    data = _get_json(url)
    spans = data.get("data", [])
    log.info("Fetched %d spans from Phoenix (since=%s strategy=%s)", len(spans), since, strategy)
    return spans


def _fetch_annotations(span_ids: list[str]) -> dict[str, list[dict]]:
    """Fetch annotations for the given span IDs. Returns {span_id: [annotation, ...]}."""
    if not span_ids:
        return {}

    # Phoenix accepts up to 100 span IDs per request — chunk if needed
    result: dict[str, list[dict]] = {}
    chunk_size = 100
    for i in range(0, len(span_ids), chunk_size):
        chunk = span_ids[i : i + chunk_size]
        params = urlencode([("span_id", sid) for sid in chunk])
        url = f"{_phoenix_base()}/v1/span_annotations?{params}"
        data = _get_json(url)
        for ann in data.get("data", []):
            sid = ann.get("span_id", "")
            result.setdefault(sid, []).append(ann)

    return result


def _build_record(span: dict, annotations: list[dict]) -> dict:
    """Merge span metadata with its annotations into one flat record."""
    labels: dict[str, str] = {}
    scores: dict[str, float] = {}
    reasons: list[str] = []
    annotated_by: str | None = None
    annotated_at: str = ""

    for ann in annotations:
        name = ann.get("name", "")
        result = ann.get("result", {}) or {}
        label = result.get("label")
        score = result.get("score")
        if label is not None:
            labels[name] = str(label)
        if score is not None:
            try:
                scores[name] = float(score)
            except (TypeError, ValueError):
                pass
        if result.get("explanation"):
            reasons.append(result["explanation"])
        if ann.get("annotator_kind") and not annotated_by:
            annotated_by = ann.get("annotator_kind")
        if ann.get("updated_at") and ann["updated_at"] > annotated_at:
            annotated_at = ann["updated_at"]

    attrs = span.get("attributes", {})
    return {
        "trace_id": span.get("context", {}).get("trace_id", ""),
        "span_id": span.get("context", {}).get("span_id", ""),
        "span_name": span.get("name", ""),
        "input": attrs.get("input.value") or attrs.get("llm.input_messages"),
        "output": attrs.get("output.value") or attrs.get("llm.output_messages"),
        "labels": labels,
        "scores": scores,
        "reason": "; ".join(reasons) if reasons else None,
        "annotated_by": annotated_by,
        "annotated_at": annotated_at,
    }


def export(
    since: str,
    *,
    strategy: str | None = None,
    out_dir: Path = _DEFAULT_NEXTCLOUD,
    dry_run: bool = False,
    project_name: str = "default",
) -> list[dict]:
    """
    Export Phoenix annotations since `since` to a JSONL file.

    Args:
        since:        ISO date string, e.g. "2026-05-20".
        strategy:     Filter to spans whose workflow_name attribute matches.
        out_dir:      Directory to write the JSONL file (default: Nextcloud path).
        dry_run:      If True, print rows to stdout, do not write to disk.
        project_name: Phoenix project name (default: "default").

    Returns:
        List of exported record dicts.
    """
    spans = _fetch_annotated_spans(since, strategy, project_name)
    span_ids = [s.get("context", {}).get("span_id", "") for s in spans if s.get("context")]
    annotations_by_span = _fetch_annotations(span_ids)

    records: list[dict] = []
    for span in spans:
        sid = span.get("context", {}).get("span_id", "")
        anns = annotations_by_span.get(sid, [])
        if not anns:
            continue  # only export labelled spans
        records.append(_build_record(span, anns))

    log.info("Built %d records with annotations", len(records))

    if dry_run:
        for rec in records:
            print(json.dumps(rec, ensure_ascii=False))
        return records

    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date_str}.jsonl"
    with out_path.open("a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    log.info("Wrote %d records to %s", len(records), out_path)
    return records


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)

    parser = argparse.ArgumentParser(
        description="Export Phoenix span annotations to Nextcloud JSONL"
    )
    parser.add_argument("--since", required=True, help="ISO date, e.g. 2026-05-20")
    parser.add_argument("--strategy", default=None, help="Filter by workflow strategy name")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_DEFAULT_NEXTCLOUD,
        help=f"Output directory (default: {_DEFAULT_NEXTCLOUD})",
    )
    parser.add_argument("--project", default="default", help="Phoenix project name")
    parser.add_argument("--dry-run", action="store_true", help="Print records, do not write")
    args = parser.parse_args()

    try:
        records = export(
            args.since,
            strategy=args.strategy,
            out_dir=args.out_dir,
            dry_run=args.dry_run,
            project_name=args.project,
        )
    except RuntimeError as exc:
        log.error("%s", exc)
        sys.exit(1)

    if not args.dry_run:
        print(f"Exported {len(records)} annotated spans.")


if __name__ == "__main__":
    main()
