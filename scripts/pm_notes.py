"""Write `docs/pm/` from the active work unit, so project state is readable and navigable.

Adapted on 2026-11-23 from the same script in the maintainer's `doctool` repository. What
differs is listed at the foot of `docs/PLANNING_WORKFLOW.md`.

`.claude/work/<id>/state.json` is the machine's task list and nobody outside the session can
read it. This renders it as Obsidian notes, so "what is done, what is left, what is waiting on
me" has an answer that is not a chat message.

## What is generated and what is not

**Generated, overwritten on every run:** `_Board.md` and one `TASK-*.md` per task. Each carries
`generated: true` and says edits are lost. The source is `state.json`.

**Hand-written, never touched here:** `README.md`, `epic.md`, `_Archive.md` and everything
under `decisions/`. A decision is an argument, and an argument is written by a person. The one
exception is the archive below: it moves `epic.md`, and rewrites its links so that they still
point at the same files.

The two are separate **files**, never two halves of one. A render mixed with hand-written prose
loses the prose the first time it is regenerated.

## One epic at a time, and the previous one is archived rather than deleted

`docs/pm/` holds the **active epic**. When `ACTIVE_WORK` names a different one, the old
epic's task notes, its board and its `epic.md` move to `docs/pm/archive/<epic>/`, and the board
starts again. **Nothing is deleted**, so an old cycle can still be opened, and the board only
ever shows the epic being worked on. **Decisions stay in `decisions/`**: `DECISIONS.md`, the
backlog and the `docs/eval/` pages cite them as the reason for what was built, and the board
lists only the open ones. In the repository this script came from, they moved with their epic
until 2026-11-22, and 47 of the 59 links to them pointed nowhere.

Every file is read and written as UTF-8 with `\n` line ends, on every system: Windows' default
encoding cannot read the notes' arrows and dashes, and its line ends would change every
generated note at each run.

Archiving happens at the **start of a new epic**, not at ship. A shipped epic stays on the
board until something replaces it, which is when you most want to look at it.

Run it:

    make pm            # .venv/bin/python scripts/pm_notes.py
"""
from __future__ import annotations

import json
import posixpath
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PM = ROOT / "docs" / "pm"
ARCHIVE = PM / "archive"
WORK = ROOT / ".claude" / "work"

#: A Markdown link in a note, `[words](target)`: its opening, its target and its close.
LINK = re.compile(r"(\]\()([^)\s]+)(\))")

#: `state.json` status to the word the board shows. Six, because a reader scanning a column
#: needs to tell "nobody has started" from "somebody is blocked", and "done" from "dropped".
STATUS = {"completed": "done", "pending": "todo", "in_progress": "doing",
          "blocked": "blocked", "partly_completed": "partly", "skipped": "dropped"}

#: The seven task types of `/plan`'s sizing table. A task without one shows a blank column.
KIND = {"contract": "contract", "mechanism": "mechanism", "wiring": "wiring", "data": "data",
        "measurement": "measurement", "checkpoint": "checkpoint",
        "documentation": "documentation"}

HEADER = ("> [!warning] Generated from `.claude/work/{unit}/state.json` by "
          "`scripts/pm_notes.py`.\n> Anything written here by hand is lost on the next run.\n")

UNFINISHED = ("todo", "doing", "blocked", "partly")

#: Who each unfinished state is waiting on. **Every row of the board names an actor**, because
#: a board that lists work without saying whose it is reads as a list of things the reader must
#: do. Only a `decisions/` note ever waits on the project owner; a task never does.
WAITING_ON = {"todo": "the assistant", "doing": "the assistant",
              "partly": "the assistant", "blocked": "another task", "done": "—",
              "dropped": "—"}


def is_decision(note: Path) -> bool:
    """Whether a file under `decisions/` is a decision, rather than the folder's own index.

    `README.md` documents the shape of a decision note and shows a `status: open` front matter
    as its example. Counted as a decision it appears on the board as an open argument blocking
    `TASK-004`, and archived with the epic it leaves the folder with no index.
    """
    return note.name != "README.md" and not note.name.startswith("_")


def active_unit() -> str:
    """The work unit `docs/pm/` is about, from `.claude/work/ACTIVE_WORK`."""
    return (WORK / "ACTIVE_WORK").read_text(encoding="utf-8").strip()


def unit_on_disk() -> str:
    """Which epic the notes currently in `docs/pm/` belong to, or empty when there are none.

    Read from a task note's `sprint:` line rather than from a file of its own. A separate
    marker file can disagree with the notes beside it, and then nothing says which is right.
    """
    for note in sorted(PM.glob("TASK-*.md")):
        for line in note.read_text(encoding="utf-8").splitlines():
            if line.startswith("sprint:"):
                return line.split(":", 1)[1].strip()
    return ""


def archive(previous: str) -> int:
    """Move the previous epic's task notes, its board and its `epic.md` into `archive/<epic>/`,
    and return how many moved. Each moved note's links are rewritten by `relinked`, so that they
    point at the same files from the archive. The decisions stay in `decisions/`.

    **Moved, never deleted.** An old cycle stays openable; it just stops being on the board.
    """
    if not previous:
        return 0
    target = ARCHIVE / previous
    target.mkdir(parents=True, exist_ok=True)
    moved = 0
    for note in list(PM.glob("TASK-*.md")) + [PM / "_Board.md", PM / "epic.md"]:
        if note.exists():
            text = relinked(note.read_text(encoding="utf-8"), _posix(PM), _posix(target))
            (target / note.name).write_text(text, encoding="utf-8", newline="\n")
            note.unlink()
            moved += 1
    return moved


def relinked(text: str, old: str, new: str) -> str:
    """`text` of a note that moves from the folder `old` to the folder `new`, each a POSIX path
    from the repository's root, with each relative Markdown link rewritten to point at the same
    file from `new`. A link to a web page or to an anchor stays, and so does a wikilink, which
    Obsidian finds by name. The paths are POSIX on every system, so a note archived on Windows
    links as one archived on Linux. In the repository this script came from, the archive
    moved the notes two folders deeper and kept their links as written until 2026-11-22, and
    26 links of the archived `epic.md` files pointed nowhere."""

    def moved(found: re.Match[str]) -> str:
        target = found.group(2)
        if target.startswith(("http:", "https:", "mailto:", "#", "/")):
            return found.group(0)
        path, mark, anchor = target.partition("#")
        to = posixpath.relpath(posixpath.normpath(posixpath.join(old, path)), new)
        return f"{found.group(1)}{to}{mark}{anchor}{found.group(3)}"

    return LINK.sub(moved, text)


def _posix(folder: Path) -> str:
    """`folder` as a POSIX path from the repository's root."""
    return folder.relative_to(ROOT).as_posix()


def file_link(path: str) -> str:
    """One file a task touched: a wikilink when a note sits at the other end, else code.

    `docs/RETRIEVAL.md` becomes `[[RETRIEVAL]]`, joining a task to the page it changed. A Python
    module or a template stays code: there is no note to open and a link that does not resolve
    is worse than none.
    """
    if path.endswith(".md") and path.split("/")[0] == "docs":
        return f"[[{Path(path).stem}]] — `{path}`"
    return f"`{path}`"


def task_note(task: dict, unit: str) -> str:
    """One task: what it owes, what it did, and what it touched."""
    status = STATUS.get(task["status"], task["status"])

    lines = ["---", "type: pm-task", f"epic: {unit}", f"sprint: {unit}",
             f"task: {task['id']}", f"status: {status}",
             f"kind: {KIND.get(task.get('type', ''), task.get('type', ''))}",
             f"title: {json.dumps(task['title'])}", "generated: true",
             f"waiting_on: {WAITING_ON.get(status, '?')}",
             f"tags: [pm/task, pm/{status}]",
             "---", "", HEADER.format(unit=unit),
             f"# {task['id']} — {task['title']}", "",
             (f"**Epic:** [[epic]] · **Status:** `{status}` · "
              f"**Waiting on:** {WAITING_ON.get(status, '?')} · **Board:** [[_Board]]"), ""]

    if task.get("notes"):
        lines += ["## Why it exists", "", task["notes"].strip(), ""]
    lines += ["## Acceptance criteria", ""]
    ticked = "x" if task["status"] == "completed" else " "
    lines += [f"- [{ticked}] {item}" for item in task.get("acceptance", [])]
    if task.get("dependencies"):
        lines += ["", "**Depends on:** " + ", ".join(f"[[{d}]]" for d in task["dependencies"])]
    if task.get("outcome"):
        lines += ["", "## What was built", "", task["outcome"].strip()]
    lines += ["", "## Files it touched", ""]
    lines += [f"- {file_link(f)}" for f in task.get("files", [])] or ["- not recorded"]
    return "\n".join(lines) + "\n"


def task_table(tasks: list[dict], wanted: tuple[str, ...]) -> str:
    """A plain Markdown table of the tasks in `wanted` states.

    **Written out rather than queried.** The board is generated from the same file the tasks
    are, so a static table is correct the moment it is written and needs no plugin. The
    Dataview blocks below it are an alternative view, not the only way to read the page.
    """
    picked = [t for t in tasks if STATUS.get(t["status"], "todo") in wanted]
    if not picked:
        return "*None.*"
    rows = ["| Task | Status | Waiting on | Kind | What it is |",
            "|---|---|---|---|---|"]
    for task in picked:
        word = STATUS.get(task["status"], task["status"])
        rows.append(f"| [[{task['id']}]] | `{word}` | {WAITING_ON.get(word, '?')} | "
                    f"{KIND.get(task.get('type', ''), '')} | {task['title']} |")
    return "\n".join(rows)


def decision_table() -> tuple[str, bool]:
    """The open decisions, and whether any of them blocks a task.

    Returns `(table, blocks_a_task)`. They are hand-written and this script never writes
    them, so it lists what is on disk.

    **Each row prints what the decision blocks**, from the note's own `blocks:` line. A board
    that says in fixed prose that no decision blocks the work is false the day one does, and an
    owner reading it takes every decision as optional. A claim about the state is derived from
    the same field the column prints.
    """
    folder = PM / "decisions"
    if not folder.exists():
        return "*None.*", False
    rows = ["| Decision | Waiting on | Blocks |", "|---|---|---|"]
    blocking = False
    for note in sorted(folder.glob("*.md")):
        if not is_decision(note):
            continue
        text = note.read_text(encoding="utf-8")
        if "status: open" not in text:
            continue
        title = next((line[2:].strip() for line in text.splitlines()
                      if line.startswith("# ")), note.stem)
        who = next((line.split(":", 1)[1].strip() for line in text.splitlines()
                    if line.startswith("waiting_on:")), "?")
        blocks = next((line.split(":", 1)[1].strip() for line in text.splitlines()
                       if line.startswith("blocks:")), "?")
        if "TASK-" in blocks:
            blocking = True
            blocks = ", ".join(f"[[{part.strip()}]]" if part.strip().startswith("TASK-")
                               else part.strip() for part in blocks.split(","))
        rows.append(f"| [[{note.stem}|{title}]] | {who} | {blocks} |")
    return ("\n".join(rows) if len(rows) > 2 else "*None.*"), blocking


def board(tasks: list[dict], unit: str) -> str:
    """The one page to open."""
    counted: dict[str, int] = {}
    for task in tasks:
        word = STATUS.get(task["status"], "todo")
        counted[word] = counted.get(word, 0) + 1
    summary = " · ".join(f"{n} {word}" for word, n in sorted(counted.items()) if word != "done")
    header = HEADER.format(unit=unit)
    unfinished = task_table(tasks, UNFINISHED)
    done = task_table(tasks, ("done",))
    decisions, blocking = decision_table()
    consequence = ("**One of them blocks a task below**, named in its own row: until it is "
                   "settled that work cannot start." if blocking else
                   "None of them blocks the work below.")
    return f"""---
type: pm-board
epic: {unit}
sprint: {unit}
generated: true
tags: [pm/board]
---

{header}
# Board — the active epic

**[[epic|{unit}]]** · **{counted.get('done', 0)} of {len(tasks)} done**{' · ' + summary if summary else ''}

[[epic|Why this epic]] · [[_Archive|Finished epics]] · [[BACKLOG|What is open, in order]]

## Waiting on the project owner

**This is the only section that is yours.** Each is an argument a person has to settle.
{consequence}

{decisions}

## Not finished — the assistant's work, not the owner's

Nothing in this table needs the project owner. It is what the coding assistant has still to
do, and it is here so the state is visible, not so anyone else acts on it.

{unfinished}

## Done

{done}

---

## The same, as live queries

These need the Dataview plugin. **They query by tag, not by folder**, so they work wherever
the vault is rooted. A folder source such as `FROM "docs/pm"` only resolves when the vault is
opened at the repository root, which is the usual reason a table comes back empty.

Without the plugin these render as code blocks, and the tables above are the board.

```dataview
TABLE status, kind, title
FROM #pm/task
WHERE status != "done"
SORT status ASC
```

```dataview
TABLE waiting_on AS "waiting on"
FROM #pm/decision
WHERE status = "open"
```
"""


def main() -> int:
    # It prints UTF-8 whatever the console's code page: its lines hold dashes, and a unit's
    # or a path's name may hold any letter.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    marker = WORK / "ACTIVE_WORK"
    if not marker.exists():
        print("no .claude/work/ACTIVE_WORK — nothing is in flight. Run /explore <proposal>.")
        return 1
    unit = active_unit()
    # An empty marker is the state `/ship` leaves behind, and the state before the first unit.
    # It is not the same as a missing one. Without this branch the empty string became a path and the message named a unit
    # that does not exist: `" has no state.json"`, with a leading space where the id belongs.
    if not unit:
        print(".claude/work/ACTIVE_WORK is empty — no work unit is open. Run /explore <proposal>.")
        return 1
    state_file = WORK / unit / "state.json"
    if not state_file.exists():
        print(f"{unit} has no state.json — it has been explored but not planned. Run /plan.")
        return 1

    previous = unit_on_disk()
    PM.mkdir(parents=True, exist_ok=True)

    if previous and previous != unit:
        moved = archive(previous)
        print(f"archived {moved} note(s) of {previous} -> docs/pm/archive/{previous}/")
        print("Add a line to docs/pm/_Archive.md and write a new docs/pm/epic.md.")

    state = json.loads(state_file.read_text(encoding="utf-8"))

    # A note left over from a task that no longer exists is removed. A stale note is worse
    # than a missing one: it reads as current.
    wanted = {f"{task['id']}.md" for task in state["tasks"]}
    for stale in PM.glob("TASK-*.md"):
        if stale.name not in wanted:
            stale.unlink()
            print(f"removed stale {stale.name}")

    for task in state["tasks"]:
        (PM / f"{task['id']}.md").write_text(task_note(task, unit), encoding="utf-8", newline="\n")
    (PM / "_Board.md").write_text(board(state["tasks"], unit), encoding="utf-8", newline="\n")

    print(f"{len(state['tasks'])} task note(s) + the board -> {PM}")
    print(f"active epic: {unit}")
    if not (PM / "epic.md").exists():
        print("no docs/pm/epic.md yet — write one: why this epic, in a person's words.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
