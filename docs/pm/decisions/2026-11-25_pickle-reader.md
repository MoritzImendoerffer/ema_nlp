---
type: pm-decision
epic: 2026-11-23_27_pipeline-refresh
status: open
opened: 2026-11-25
waiting_on: the lead assistant session, or the owner
blocks: TASK-010
tags: [pm/decision]
---

# G. What happens to the pickle reader once `parse-pdfs` reads PDF bytes

Written by Claude (Opus 5.5) during `/plan` on 2026-11-25. The proposal's sketch says that "the
legacy reader keeps the name `legacy_pickle` and leaves the pipeline's steps". Decision D kept
the name `pymupdf4llm` for the legacy rows, so the sketch no longer says what the reader
becomes.

## What was found

- `corpus/parsers/pymupdf4llm.py` is the pickle reader today. It unpickles the scraper's
  `parsed_pdf.pkl` holders (`pickle.loads`, line 100) and writes rows named `pymupdf4llm`.
  Its `parser_version` is the **installed** library version, `version("pymupdf4llm")` =
  `1.27.2.3` (lines 50-57), although the text in the pickles was made by `pymupdf4llm 0.2.9`
  (exploration, section 3.2).
- `scripts/ingest_parsed_pdfs.py:29` imports that reader's `_cli`. Its default mode writes to
  `parsed_documents`. Its `--legacy` mode writes to the older `parsed_pdfs` collection.
- The new byte parser writes `(url, pymupdf4llm, 1.27.2.3)`. That is the **same key** as the
  pickle reader's rows. Whichever tool ran last would overwrite the other's row for a URL, and
  a pickle row would carry a version that did not make its text.

## The options

| | What changes | What it means |
|---|---|---|
| **G1** | The pickle path to `parsed_documents` is removed. `corpus/parsers/pymupdf4llm.py` parses bytes only. The default mode of `scripts/ingest_parsed_pdfs.py` delegates to the byte parser (it does so through `_cli` already), and `--legacy` stays as it is | No tool writes a mislabelled row. The legacy text stays where it is: 58,121 rows in `parsed_documents`, and `parsed_pdfs.markdown` |
| **G2** | The pickle reader moves into `scripts/ingest_parsed_pdfs.py` as parser `legacy_pickle`, with the tool version the pickle records (`pymupdf4llm 0.2.9`, or `unknown`) | A third row family per PDF. It is not in the preference file, so decision F uses it only for a URL that has no other row |
| **G3** | The pickle reader writes the legacy key `(pymupdf4llm, legacy)` | Running it overwrites the 58,121 legacy rows. The exploration (section 4.1) says that no step should do that |

## Recommendation

**G1.** It is the smallest change. It follows rule 1 (build only what the proposal asks), and
it leaves no tool that can write a wrong label. Nothing in the pipeline needs the pickles once
the parser reads `response_body`.

TASK-010 waits for this answer. Every other task can go on without it.

## The answers

*(open)*
