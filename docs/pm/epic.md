---
type: pm-epic
epic: 2026-11-23_27_pipeline-refresh
status: in-progress
opened: 2026-11-23
tags: [pm/epic]
---

# Pipeline refresh: the newest parse wins, a changed document is replaced

Written by Claude (Opus 5.5) during `/plan` on 2026-11-25. This note is hand-written;
`scripts/pm_notes.py` never changes it.

**Backlog row 10**, top of `Now` in [`BACKLOG.md`](../../BACKLOG.md) ·
proposal: [`docs/next/pipeline_refresh.md`](../next/pipeline_refresh.md) ·
plan: `.claude/work/2026-11-23_27_pipeline-refresh/implementation-plan.md` ·
board: [[_Board]]

## Why this epic

The corpus repair of backlog row 11 will re-parse about 22,700 HTML pages and 7,565 PDFs. None of
that could reach the graph today. `scripts/update_graph.py` adds documents that are new and cannot
change one that exists:

- the PDF step loads the scraper's pickles and fails on every PDF;
- a new parse of a URL never wins over the old one;
- a changed document is skipped, and a removed one stays;
- a fresh build loses the document labels;
- `--reset` deletes the whole graph, the NeoDash dashboard included, in one transaction.

This epic makes the graph refreshable. Each document records which parse built it. The build
picks the preferred and newest parse per URL, replaces a document whose text changed, skips the
others, and parses PDF bytes in this repository. Deleting from the live graph is new here, so the
deletes run on a throwaway Neo4j first, and each live run waits for the owner's yes.

## Who decided what

Decisions A, B, D, E and F were taken on 2026-11-25 by the lead assistant session under the
owner's delegation. They are labelled so in their notes under [`decisions/`](decisions/), and the
owner can overrule each one. Decision G and the go-ahead for the two live runs are open.
