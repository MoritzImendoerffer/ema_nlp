"""scripts/update_graph.py, the pipeline's entry point, in dry-run mode (work unit 27).

Until 2026-11-25 the script had no test, and its parse-pdfs step ran a parser that
failed on every PDF. A dry run prints the commands and runs none of them.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

_REPO = Path(__file__).resolve().parents[1]


def _dry_run(*args: str) -> str:
    result = subprocess.run(
        [sys.executable, str(_REPO / "scripts" / "update_graph.py"), "--dry-run", *args],
        capture_output=True, text=True, cwd=_REPO, check=True,
    )
    return result.stdout


def test_dry_run_lists_parse_pdfs(tmp_path):
    out = _dry_run("--pdf-cache", str(tmp_path))
    assert f"corpus.parsers.pymupdf4llm --cache {tmp_path}" in out
    assert "dry run" in out


def test_dry_run_forwards_prune():
    out = _dry_run("--steps", "build", "--prune")
    build_line = next(line for line in out.splitlines() if "harness.indexing.build" in line)
    assert build_line.rstrip().endswith("--prune")


def test_build_cli_forwards_prune(monkeypatch):
    import harness.indexing.build as build_cli

    seen: dict = {}
    monkeypatch.setattr(build_cli, "build_index", lambda profile, **kw: seen.update(kw))
    monkeypatch.setattr(build_cli, "configure_embed_model", lambda *a, **k: None)
    monkeypatch.setattr(build_cli, "Settings", SimpleNamespace(embed_model=None))
    monkeypatch.setattr(sys, "argv", ["build", "--limit", "1", "--prune", "--embed-device", "cpu"])
    build_cli.main()
    assert seen["prune"] is True and seen["reset"] is False


def test_build_help_says_what_reset_deletes():
    result = subprocess.run(
        [sys.executable, "-m", "harness.indexing.build", "--help"],
        capture_output=True, text=True, cwd=_REPO, check=True,
    )
    help_text = " ".join(result.stdout.split())
    assert "--prune" in help_text
    assert "Document and Chunk" in help_text and "batches" in help_text
