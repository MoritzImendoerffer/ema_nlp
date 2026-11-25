---
type: pm-task
epic: 2026-11-23_27_pipeline-refresh
sprint: 2026-11-23_27_pipeline-refresh
task: TASK-015
status: blocked
kind: checkpoint
title: "Checkpoint: report the code and the measurement, and ask for the two live runs"
generated: true
waiting_on: another task
tags: [pm/task, pm/blocked]
---

> [!warning] Generated from `.claude/work/2026-11-23_27_pipeline-refresh/state.json` by `scripts/pm_notes.py`.
> Anything written here by hand is lost on the next run.

# TASK-015 — Checkpoint: report the code and the measurement, and ask for the two live runs

**Epic:** [[epic]] · **Status:** `blocked` · **Waiting on:** another task · **Board:** [[_Board]]

## Why it exists

The proposal's last paragraph: the replace step and the reset are the first code here that deletes from the live graph; the first live run is a data task on one document, with the counts before and after. CLAUDE.md rule 4: ask before a run that deletes.

A finding for the note: under decision A a byte parse of a URL that has a legacy row does not replace it, so a one-URL run cannot exercise the live replace by itself. Two shapes to offer: (a) one of the gzip PDFs, which have no legacy row: the byte parser decompresses it, the build adds one new document, every other document is skipped; (b) one legacy PDF, parsed with the byte parser, with the PDF list of parser_preference.yaml put in the other order for one build: exactly that URL has a row of the new parser, so exactly one document is replaced; restoring the file and building again puts the legacy text back. (b) edits an authored file for one run, so it needs the owner's explicit yes.

The read-only dry run is allowed without asking: it writes to neither store.

## Acceptance criteria

- [ ] docs/pm/decisions/2026-11-25_live-graph-runs.md exists with status open and states, for the backfill and for the one-URL run: the counts before and after, the hours, the way back, and 0 paid model calls
- [ ] The backfill's hours come from `scripts/backfill_parse_identity.py --dry-run --limit 1000` on the live stores (read-only), scaled to 79,882 documents, with the arithmetic written out
- [ ] The owner (or the lead session, if the owner delegates it) has answered in the note; TASK-016 does not start before

**Depends on:** [[TASK-010]], [[TASK-011]], [[TASK-012]], [[TASK-014]], [[TASK-018]]

## What was built

Checkpoint reached 2026-11-25. Findings: docs/eval/2026-11-25_graph_delete_measurement.md, section 'Checkpoint' (full read-only backfill dry run: 80,078 URLs in 8.0 s, 11.1 s wall; would stamp 79,882; 0 old-rule rows differ; 0 prune candidates; cache walk 5 s). Decision note opened: docs/pm/decisions/2026-11-25_live-graph-runs.md (status open, waiting on the owner): the backfill, and one URL through the pipeline in shape (a) gzip PDF / add path or (b) legacy PDF with the preference swapped for one build / replace path; recommendation: backfill, then (b). Acceptance 1 and 2 met; acceptance 3 (the owner's answer) is open, so TASK-016 and TASK-017 do not start.

## Files it touched

- [[2026-11-25_live-graph-runs]] — `docs/pm/decisions/2026-11-25_live-graph-runs.md`
- [[2026-11-25_graph_delete_measurement]] — `docs/eval/2026-11-25_graph_delete_measurement.md`
