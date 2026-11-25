---
type: pm-decision
epic: 2026-11-23_27_pipeline-refresh
status: settled
settled: 2026-11-25
opened: 2026-11-23
waiting_on: the owner (may overrule)
blocks: TASK-002
tags: [pm/decision]
---

# F. A URL whose clean rows all come from a parser the preference file does not list

Open question F of the exploration (`.claude/work/2026-11-23_27_pipeline-refresh/exploration.md`,
section 3.5).

## What was found

No such URL exists today. The 5 `llamahub_pdf_PDFReader` rows share their URLs with
`pymupdf4llm` rows. They are fixtures (`meta: {synthetic: true, note: "MIGR-015 smoke
fixture"}`) left in the live collection.

## The options

1. Fall back to the newest clean row, log a warning and count the URLs.
2. Skip the URL and count it.

## The answers

**2026-11-25, decided by the lead assistant session `ema-nlp-3b` under the owner's delegation
of 2026-11-25** ("You are allowed to plan and implement ways forward"), relayed to the
implementing session. This is the assistant's answer, not the owner's. The owner can overrule
it.

Option 1, the recommendation. A parser that somebody forgot to list must not remove documents
from a build without a trace. The build prints the count of such URLs at its end.
