#!/usr/bin/env python3
"""Render past MLflow traces as retrieval-chain HTML (see docs/VISUALIZATION.md).

Rebuilds the tool-call chain from a trace's autolog spans
(``harness.export.chain_from_trace``) and renders it with the same
``chain_html`` exporter the live app uses — so "how did the chain evolve?" is
answerable for any recorded turn, including whole eval runs.

Usage::

    python scripts/render_trace.py <trace_id> [--out <dir>]
    python scripts/render_trace.py --run-id <mlflow_run_id>   # all traces of an eval run
    python scripts/render_trace.py <trace_id> --tracking-uri sqlite:///mlflow.db

Defaults: tracking URI from $MLFLOW_TRACKING_URI (else the repo's mlflow.db),
output under ``config.RESULTS_DIR / chains/`` (the Nextcloud-synced results
folder, so rendered chains show up on every machine).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _traces(args: argparse.Namespace) -> list:
    import mlflow

    if args.run_id:
        # search_traces only looks in experiment 0 unless told where the run lives.
        experiment_id = mlflow.get_run(args.run_id).info.experiment_id
        found = mlflow.search_traces(
            run_id=args.run_id,
            locations=[experiment_id],
            return_type="list",
            max_results=args.max_traces,
        )
        if not found:
            raise SystemExit(f"No traces found for run_id {args.run_id!r}")
        return list(found)
    trace = mlflow.get_trace(args.trace_id)
    if trace is None:
        raise SystemExit(f"Trace not found: {args.trace_id!r}")
    return [trace]


def main(argv: list[str] | None = None) -> int:
    import config

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("trace_id", nargs="?", help="MLflow trace id (tr-…)")
    parser.add_argument("--run-id", help="Render every trace of this MLflow run (eval runs)")
    parser.add_argument(
        "--out",
        default=str(config.RESULTS_DIR / "chains"),
        help="output directory (default: Nextcloud-synced results dir)",
    )
    parser.add_argument("--tracking-uri", default=None, help="MLflow tracking URI")
    parser.add_argument("--export-config", default="default", help="configs/export/<name>.yaml")
    parser.add_argument("--max-traces", type=int, default=100)
    args = parser.parse_args(argv)
    if bool(args.trace_id) == bool(args.run_id):
        parser.error("give exactly one of <trace_id> or --run-id")

    import mlflow

    uri = args.tracking_uri or os.getenv(
        "MLFLOW_TRACKING_URI", f"sqlite:///{REPO_ROOT / 'mlflow.db'}"
    )
    mlflow.set_tracking_uri(uri)

    from harness.export import ChainHtmlExporter, load_export_options
    from harness.export.chain_from_trace import bundle_from_trace

    options = load_export_options(args.export_config)
    exporter = ChainHtmlExporter()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for trace in _traces(args):
        bundle = bundle_from_trace(trace)
        trace8 = (bundle.trace_id or "trace").removeprefix("tr-")[:8]
        path = out_dir / f"chain_{trace8}.html"
        path.write_text(exporter.render(bundle, options), encoding="utf-8")
        n_steps = len(bundle.chain)
        print(f"{path}  ({n_steps} step(s), question: {bundle.question[:60]!r})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
