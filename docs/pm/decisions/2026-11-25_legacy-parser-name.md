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

# D. How the legacy PDF rows and the new byte parser are told apart

Open question D of the exploration (`.claude/work/2026-11-23_27_pipeline-refresh/exploration.md`,
section 3.1).

## What was found

No parser is named `legacy_pickle`, although the proposal's sketch assumed one. The store:

```
db.parsed_documents.aggregate([{$group: {_id: {content_type, parser, parser_version}, n: {$sum: 1}}}])
  application/pdf  pymupdf4llm             legacy   58,121
  text/html        trafilatura             legacy   21,957
  application/pdf  llamahub_pdf_PDFReader  0.6.0         5
```

(re-run read-only on 2026-11-25: 80,083 rows, as in the exploration.) The new byte parser
writes `(url, pymupdf4llm, 1.27.2.3)`. A rule of "preferred parser name, then newest
`parsed_at`" would pick the new row over the legacy row, whatever decision A says.

## The options

- **D1.** A preference entry may name a version: `pymupdf4llm@legacy` before `pymupdf4llm`.
  No write to a store.
- **D2.** Rename the 58,121 rows to `parser: legacy_pickle`: one `update_many` on derived rows
  that no code here can write again.
- **D3.** Give the new parser another name, so that `pymupdf4llm` means "the old text" for
  good.

## The answers

**2026-11-25, decided by the lead assistant session `ema-nlp-3b` under the owner's delegation
of 2026-11-25** ("You are allowed to plan and implement ways forward"), relayed to the
implementing session. This is the assistant's answer, not the owner's. The owner can overrule
it.

D1, the recommendation. An entry `name` matches every version of that parser. An entry
`name@version` matches that version only. The backfill stamps what the rows say:
`parser: pymupdf4llm`, `parser_version: legacy`.
