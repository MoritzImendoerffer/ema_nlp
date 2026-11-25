"""scripts/update_graph.py, the pipeline's entry point, in dry-run mode (work unit 27).

Until 2026-11-25 the script had no test, and its parse-pdfs step ran a parser that
failed on every PDF. A dry run prints the commands and runs none of them.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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
