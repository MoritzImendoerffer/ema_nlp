# docs/next — proposals, one file each

> **This folder is not a queue.** Which proposal is next, and what is parked and why, is
> [`BACKLOG.md`](../../BACKLOG.md) at the repo root. A proposal is the detail behind a backlog
> row. How a proposal becomes delivered work is in
> [`../PLANNING_WORKFLOW.md`](../PLANNING_WORKFLOW.md).

**A file here is not a commitment.** It says what would be built and how it would be checked,
so the decision can be made on paper instead of in an editor.

**A file here is deleted when the work ships.** `/ship` moves its content into `docs/`,
`DECISIONS.md` and the README, and removes the proposal. `git` keeps the history, and a plan
that no longer matches the code is worse than no plan. This rule holds since 2026-11-23;
`topic_subgraphs.md` landed before it and is kept as history.

## What a proposal contains

The title is followed by a `**Status:**` line: `proposed <date>`, the backlog row, and the work
unit once `/explore` has opened one.

| Section | Why |
|---|---|
| **The problem** | with the example that showed it, not an opinion |
| **The idea** | one paragraph before any detail |
| **What it deliberately does not do** | the limits, stated by the author rather than discovered by the reader |
| **Implementation sketch** | files, stored shapes, rough size |
| **Verification** | how anyone would know it worked: test names, commands, read-only queries with the expected number |
| **Open questions** | what the author could not decide, each with the options and a recommendation |
| **For the implementing session** | what that session must verify or may decide otherwise, since a proposal is often written by one session and implemented by another |

A proposal that cites the code, a store, another repository or a library API cites the file,
the query or the version, not the memory. `/explore` checks those claims before anything is
planned. A proposal carries the plan's class and ladder labels (C1 to C9, E0 to E9) and public
EMA content, and nothing else of the private plan this repository rehearses.

## The proposals

| Proposal | Backlog row | Status | What it is |
|---|---|---|---|
| [`pipeline_refresh.md`](pipeline_refresh.md) | 10 | 🚧 work unit `2026-11-23_27_pipeline-refresh`; planned 2026-11-25, 18 tasks | The build picks the preferred and newest parse per URL, replaces a changed document's chunks, joins the document labels, parses PDF bytes in this repository, and resets in batches. |
| [`answer_record.md`](answer_record.md) | 18 | 📋 proposed 2026-11-25; no work unit while unit 27 is open | A claim names the passage it rests on and quotes it, four checks by plain code produce numbers per run, and an answer without claims is counted. Written after an adversarial review ([`../eval/2026-11-25_direction_review.md`](../eval/2026-11-25_direction_review.md)). |
| [`closed_book_lift.md`](closed_book_lift.md) | 3 | 📋 planned | The closed-book baseline and the **lift** metric, the benchmark's headline number. Doubles as the Phase 2.5 contamination screen. |
| [`corpus_repair.md`](corpus_repair.md) | 11 | 📋 proposed 2026-11-25; waits for row 10; first in line for `Now` | The HTML parser keeps the page body and the accordion questions, the PDF parser runs over the 7,678 cached PDFs that were never parsed, and a script compares the graph with EMA's document list before and after. Three checkpoints: one page, all HTML pages, the new PDFs. |
| [`document_metadata_and_entities.md`](document_metadata_and_entities.md) | 13 | 📋 proposed 2026-11-25; waits for rows 10 and 11 | EMA's own feed fields on `:Document` (title, status, dates, reference and product number) and a medicines table keyed by product number, without re-embedding. A second stage adds substances, classes, procedures, chunk position and the version role of file cards. |
| [`benchmark_v0.md`](benchmark_v0.md) | 15 | 📋 proposed 2026-11-25; the computed items wait for row 13 | 30 items in nine classes on four related products, one held out. Each item has must-have facts and gold sources with a quote. 11 gold answers are computed from EMA's tables, and 6 items ask for a proposal in steps. Scoring per fact, in three repeats, with the first failing stage. |
| [`error_census_and_sitting.md`](error_census_and_sitting.md) | 20 | 📋 proposed 2026-11-25; needs row 18 and the owner's time | A person labels real claims by kind of error, and the checks of row 18 are scored on those labels. A sitting follows only if wrong claims are found among the claims that passed. A pilot of 30 claims needs no code. |
| [`pdf_parsing_docling.md`](pdf_parsing_docling.md) | 17 | 📋 proposed 2026-11-25; the pilot and the rank wait for the owner | A `docling` PDF parser in its own environment (Docling 2.132.0, PP-OCRv6 for pages without text, PaddleOCR-VL or TableFormer for tables), five files per PDF in the format of the owner's repository doctool, and a pilot that parses about 270 PDFs three ways. No change to the graph; the chunker and the conversion are row 21. |
| [`tree_retrieval_followups.md`](tree_retrieval_followups.md) | 1, 2, 4, 5, 6, 8 | 🚧 step 1 done | Fix **seeding** for tree-aware retrieval. Step 1 measured it ([report](../eval/2026-07-20_tree_seeding.md)): three distinct problems, and `oversample` is gated off in the tree profile. |
| [`topic_subgraphs_followups.md`](topic_subgraphs_followups.md) | 7 | 📋 planned | Four small follow-ups to the subgraphs work: the `steered_agent` baseline, more hubs, cross-family T2 items, and an LLM request timeout. |
| [`metadata_steering.md`](metadata_steering.md) | parked | 💡 designed (gated) | Steer retrieval on EMA's own labels (`doc_type` / `audience` / `site_topic`) instead of the coarse URL `category`. |
| [`retrieval_miss_detection.md`](retrieval_miss_detection.md) | parked | 💡 designed (gated) | An exact-span probe that sorts answer spans into *grounded* / *in-corpus-but-not-retrieved* / *novel*, to separate retrieval failures from generation failures. |
| [`graphrag_vs_mcp_benchmark.md`](graphrag_vs_mcp_benchmark.md) | parked | 💡 designed (gated) | A research program comparing Vector RAG, GraphRAG, and openpharma MCP tools. Overlaps with backlog rows 14 and 16; fold it in when they get their proposals. |
| [`topic_subgraphs.md`](topic_subgraphs.md) | none | 🚧 landed (steps 1–6; eval partial) | Precomputed **topic subgraphs**. Built and evaluated live 2026-07-13 ([report](../eval/2026-07-13_topic_subgraphs.md)). History. |

The seven files from before 2026-11-23 use an older layout: why, what exists, the design, the
steps, the open decisions. `/explore` accepts them as they are.

## Backlog rows without a proposal yet

A row gets its proposal before it enters `Now`. Until then its detail is a section of the
review of 2026-11-23
([`../eval/2026-11-23_pkr_testbed_review.md`](../eval/2026-11-23_pkr_testbed_review.md)).

| Backlog row | Review section |
|---|---|
| 14 The cheap rungs: full-text search and the read tool | 7 |
| 16 The first ladder runs | 2, 11 |
| 19 The MCP servers (split from row 14 on 2026-11-25) | 7 |
| 21 Chunks from the Docling records, and the conversion of the corpus | 8, and [`pdf_parsing_docling.md`](pdf_parsing_docling.md), "What comes after" |
| 12 Docs: the setup path | 10 |

Candidates with neither a row's proposal nor a review section: learned re-ranking from citation
feedback (needs data), the ablation grid (Phase 4), and the DSPy few-shot bootstrap (needs
≥ 50 rated examples). They are parked in the backlog.
