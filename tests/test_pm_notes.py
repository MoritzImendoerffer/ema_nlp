"""The board script, `scripts/pm_notes.py`: what it does when a new epic takes `docs/pm/`. It is
the maintainer's view of the work (docs/PLANNING_WORKFLOW.md, "docs/pm/"), so it runs where
they work, Windows included. The script and this test came from the maintainer's `doctool`
repository on 2026-11-23; the findings page lives in `docs/eval/` here."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pm_notes.py"
#: The relative Markdown links of a note.
LINK = re.compile(r"\]\(([^)\s#:]+)(?:#[^)\s]*)?\)")


def repository(root):
    """A repository whose `docs/pm/` holds the epic `old-unit`, with a settled decision and an
    `epic.md` that links a findings page, the decision, a deleted proposal, a web page and an
    anchor, while `ACTIVE_WORK` names `new-unit`, whose one task's title holds an arrow and a dash
    that Windows' default encoding, cp1252, cannot read or does not hold."""
    (root / "scripts").mkdir()
    shutil.copy(SCRIPT, root / "scripts" / "pm_notes.py")
    pm = root / "docs" / "pm"
    (pm / "decisions").mkdir(parents=True)
    (root / "docs" / "eval").mkdir()
    (root / "docs" / "eval" / "r.md").write_text("# A finding\n", encoding="utf-8")
    (pm / "decisions" / "d.md").write_text(
        "---\ntype: pm-decision\nepic: old-unit\nstatus: settled\n---\n\n# Which way → A\n",
        encoding="utf-8")
    (pm / "epic.md").write_text(
        "# The old epic — shipped\n\n[the finding](../eval/r.md#top) · [the decision](decisions/d.md)"
        " · [a deleted proposal](../next/gone.md) · [a page](https://example.com/a.md)"
        " · [above](#the-old-epic)\n", encoding="utf-8")
    (pm / "TASK-001.md").write_text("---\nsprint: old-unit\n---\n\n# TASK-001 — done\n",
                                    encoding="utf-8")
    (pm / "_Board.md").write_text("# Board → old-unit\n", encoding="utf-8")
    work = root / ".claude" / "work"
    (work / "new-unit").mkdir(parents=True)
    (work / "ACTIVE_WORK").write_text("new-unit\n", encoding="utf-8")
    (work / "new-unit" / "state.json").write_text(json.dumps({"status": "implementing", "tasks": [
        {"id": "TASK-001", "title": "Read the notes → write them — on Windows too",
         "status": "pending", "type": "mechanism", "dependencies": [], "files": [],
         "acceptance": ["≥ 1 note"]}]}, ensure_ascii=False), encoding="utf-8")
    return pm


def test_a_new_epic_archives_the_old_one_and_keeps_every_link(tmp_path):
    """In the repository this script came from, the archive moved the old epic's decisions
    with its notes until 2026-11-22, so 47 of the 59 links to a decision pointed nowhere; it
    moved `epic.md` two folders deeper and kept its links as written, so 26 of the archived
    epics' links pointed nowhere too. And the script read and wrote with the system's default
    encoding: on Windows,
    cp1252, which cannot hold `→` and `≥`, and with `\\r\\n` line ends, which would change every
    generated note at each run. Python's EncodingWarning, made an error here, names each read or
    write that leaves the encoding to the system, on Linux as on Windows; the run's default
    encoding is ASCII where the system allows it, and the script's own lines, which hold a dash,
    still print."""
    pm = repository(tmp_path)

    # Python's default encoding made ASCII, stricter than Windows' cp1252, where the system allows
    # it: the C locale with UTF-8 mode off. On Windows the variables change nothing.
    ascii_default = {**os.environ, "LC_ALL": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"}
    run = subprocess.run([sys.executable, "-X", "warn_default_encoding", "-W", "error::EncodingWarning",
                          str(tmp_path / "scripts" / "pm_notes.py")],
                         cwd=tmp_path, env=ascii_default, capture_output=True, check=False)

    assert run.returncode == 0, run.stderr.decode("utf-8", "replace")
    archived = pm / "archive" / "old-unit"
    assert (pm / "decisions" / "d.md").exists() and not (archived / "decisions").exists()
    assert sorted(path.name for path in archived.iterdir()) == ["TASK-001.md", "_Board.md", "epic.md"]
    epic = (archived / "epic.md").read_text(encoding="utf-8")
    assert epic == (
        "# The old epic — shipped\n\n[the finding](../../../eval/r.md#top) · [the decision]"
        "(../../decisions/d.md) · [a deleted proposal](../../../next/gone.md) · [a page]"
        "(https://example.com/a.md) · [above](#the-old-epic)\n")
    assert [target for target in LINK.findall(epic) if not (archived / target).exists()] == [
        "../../../next/gone.md"]
    note = (pm / "TASK-001.md").read_bytes()
    assert "Read the notes → write them — on Windows too".encode() in note
    assert "≥ 1 note".encode() in note
    for written in (note, (pm / "_Board.md").read_bytes(), (archived / "epic.md").read_bytes()):
        assert b"\r\n" not in written
    assert "no docs/pm/epic.md yet — write one" in run.stdout.decode("utf-8")
