# docs/pm — the sprint you can see

`.claude/work/<id>/state.json` is the machine's task list and nobody outside the session can
read it. This folder is that file rendered as Obsidian notes: a board, one note per task, and
one note per decision that is waiting on a person.

Regenerate it:

```bash
make pm            # .venv/bin/python scripts/pm_notes.py
```

**This folder orders nothing.** What is open, and in what order, is
[`BACKLOG.md`](../../BACKLOG.md). The board shows the tasks of the one backlog row that has a
work unit open.

## Generated and hand-written are separate files

| File | Written by | Regenerated |
|---|---|---|
| `_Board.md` | `scripts/pm_notes.py` | every run. Edits are lost |
| `TASK-*.md` | `scripts/pm_notes.py` | every run. Edits are lost |
| `epic.md` | a person or `/plan` | never touched by the script |
| `decisions/*.md` | a person or `/next` | never touched by the script |
| `README.md`, `_Archive.md` | a person | never touched by the script |

A render mixed with hand-written prose loses the prose the first time it is regenerated, so the
two are never two halves of one file.

## One epic at a time

When `.claude/work/ACTIVE_WORK` names a different unit, the old epic's board, epic note and
task notes move into `archive/<epic>/`, with their links rewritten to point at the same files
from there. Its decisions stay in `decisions/`, since other documents link them; the board lists
only the open ones. Nothing is deleted.
Archiving happens when a **new** epic starts, not when one ships: a shipped epic is the one a
reader most wants to look at.

## Decisions

A note under `decisions/` is the only thing on this board addressed to the owner. Its shape is
in [`decisions/README.md`](decisions/README.md).

*The active epic is `epic.md`; the board is `_Board.md`. Both point at the work unit that
`.claude/work/ACTIVE_WORK` names. When no unit is open, neither file exists.*
