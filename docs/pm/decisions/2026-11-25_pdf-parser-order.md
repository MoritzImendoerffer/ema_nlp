---
type: pm-decision
epic: 2026-11-23_27_pipeline-refresh
status: settled
settled: 2026-11-25
opened: 2026-11-23
waiting_on: the owner (may overrule)
blocks: TASK-001
tags: [pm/decision]
---

# A. Which PDF parse the preference file names first

Open question A of the proposal (`docs/next/pipeline_refresh.md`, "Open questions") and of the
exploration (`.claude/work/2026-11-23_27_pipeline-refresh/exploration.md`, section 10).

## What was found

58,121 PDF documents in the graph were chunked and embedded from the rows
`(url, pymupdf4llm, legacy)` of `parsed_documents`. A new parse of the same PDF with the
installed `pymupdf4llm` 1.27.2.3 never gives equal text: on one 6-page PDF the legacy text has
13,036 characters and the new text 12,924, `difflib` ratio 0.994 (exploration, section 6.2).

## The options

1. **The legacy rows first, then the new parser.** A PDF that has a legacy row keeps it. Only
   a PDF without a legacy row is built from a new parse. Nothing in the graph changes until a
   later item asks for it.
2. **The new parser first.** Every PDF that is parsed again replaces its legacy text, and its
   leaves are embedded again.

## The answers

**2026-11-25, decided by the lead assistant session `ema-nlp-3b` under the owner's delegation
of 2026-11-25** ("You are allowed to plan and implement ways forward"), relayed to the
implementing session. This is the assistant's answer, not the owner's. The owner can overrule
it.

Option 1, the recommendation of the proposal and the exploration. With decision D the file
reads:

```yaml
application/pdf:
  - pymupdf4llm@legacy
  - pymupdf4llm
```

Reason: it is the low-risk option. It keeps today's graph content until someone asks for a
change, and a one-line edit of the file reverses it.
