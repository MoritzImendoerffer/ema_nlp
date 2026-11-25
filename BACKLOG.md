# Backlog — the single ranked queue of open work

**This file is the one place that answers "what's open, and what's next."** Every
other document keeps its detail; a row here is the pointer plus the status.

> **Re-ranked on 2026-11-23.** The owner decided that this repository is the rehearsal
> ground for the process-knowledge-retrieval plan ([`DECISIONS.md`](DECISIONS.md),
> "Rehearsal ground"). The order below follows the review of that day
> ([section 11](docs/eval/2026-11-23_pkr_testbed_review.md)). The ranking is the
> assistant's proposal: the owner said yes to the rehearsal, not to each line, and can
> overrule any of them.

## Rules

1. **Nothing is open unless it has a row here.** Proposals live in
   [`docs/next/`](docs/next/README.md), findings in [`docs/eval/`](docs/eval/),
   decisions in [`DECISIONS.md`](DECISIONS.md). A row links out; it never
   duplicates the content.
2. **`Now` is capped at 3.** A fourth item cannot start until one finishes or is
   explicitly demoted to `Next`. This cap is the point of the file — it forces
   the "what about the other thing?" question at planning time. At most one row has
   a work unit open: `.claude/work/ACTIVE_WORK` names it, and
   [`docs/pm/`](docs/pm/README.md) shows its tasks.
3. **A row's number is its name and never changes. The order of the rows is the
   rank.** Row 3 is the same item before and after a re-rank, so a link to it stays
   true.
4. **A row enters `Now` with a proposal in `docs/next/`.** `/explore <proposal>`
   opens its work unit, then `/plan`, `/next` and `/ship`
   ([`docs/PLANNING_WORKFLOW.md`](docs/PLANNING_WORKFLOW.md)).
5. **Closing is one move:** `/ship` deletes the row and the proposal and appends a
   line to [`.claude/HISTORY.md`](.claude/HISTORY.md), in the same commit as the
   code.
6. **Phase status stays in** [`project_roadmap/ROADMAP.md`](project_roadmap/ROADMAP.md);
   item status stays here. The roadmap links here rather than restating.

Sizes: **S** ≈ one session · **M** ≈ a few sessions · **L** ≈ a week+.

---

## Now (max 3)

| # | Task | Size | Proposal / context | Notes |
|---|---|---|---|---|
| 10 | **A pipeline that can refresh the graph** — the build picks the preferred and newest parse per URL, replaces a changed document's chunks, joins the document labels, parses PDF bytes in this repository, and resets in batches. | M | [`next/pipeline_refresh.md`](docs/next/pipeline_refresh.md) · [review](docs/eval/2026-11-23_pkr_testbed_review.md) §3.2 | **Work unit `2026-11-23_27_pipeline-refresh` opened 2026-11-23** (branch `pipeline-refresh`; planned 2026-11-25, 18 tasks; decisions A, B, D, E, F, G taken by the lead assistant session under the owner's delegation, overrulable). Step 1a. Row 11 cannot reach the graph without it. It does not depend on row 9. |
| 3 | **Closed-book baseline + lift metric** — the benchmark's headline number, and the Phase 2.5 contamination screen. | L | [`next/closed_book_lift.md`](docs/next/closed_book_lift.md) | Blocks the Phase 3 exit criteria and any honest ablation result. It stays under the rehearsal: EMA text is public, so lift remains the number to report. Row 9 (eval reliability) shipped on 2026-11-23: its runs go through the repaired runner. |

## Next (ordered)

| # | Task | Size | Proposal / context | Notes |
|---|---|---|---|---|
| 11 | **Corpus repair** — the HTML extractor drops the body of guidance pages (54% of pages under `/human-regulatory-overview/`; "Pre-authorisation guidance" is one 302-char chunk); 6,760 gzip-encoded PDFs and 805 `.pdf-N` files were never parsed; no completeness check against EMA's document feed. | M | [review](docs/eval/2026-11-23_pkr_testbed_review.md) §3.1–3.2 · proposal not written | Step 1b. Waits for row 10. First in line for `Now`. May explain part of row 4 (short hub pages): test before building row 4. |
| 13 | **Carry the metadata, and build the entity tables from EMA's own feeds** — title, dates, status, reference and product number on `:Document`; current or superseded on file-card edges; chunk order, page and section on `:Chunk`; medicines, substances and ATC codes as tables. No LLM extraction. | M | [review](docs/eval/2026-11-23_pkr_testbed_review.md) §3.3, §6 · proposal not written | Step 2. Gives the corpus its "project" (the medicinal product), version filters, and what a read-document tool needs. |
| 14 | **The cheap rungs and the MCP servers** — a full-text index, `search_documents`, `read_document`, `list_documents`, a call log on the server; one server for the documents and one for the domain layer. | M | [review](docs/eval/2026-11-23_pkr_testbed_review.md) §7 · proposal not written | Step 3. Opens E0, E1 and E2, and lets Claude Code or another agent query the corpus. The read tool needs row 13. |
| 15 | **Benchmark v0 in nine classes** — the record schema, three products plus one held out, about 30 items with computed gold answers for C5, C6 and C8; scoring by retrieval hit, must-have facts and abstention; three repeats. | M | [review](docs/eval/2026-11-23_pkr_testbed_review.md) §2, §5 · proposal not written | Step 4. An item that an assistant wrote is labelled so until the owner has reviewed it. |
| 16 | **The first ladder runs** — E0 to E2 on benchmark v0, the failures counted by their first failing stage, then E3, E4 and E5 in the order the counts give. | per run | [review](docs/eval/2026-11-23_pkr_testbed_review.md) §2, §11 · proposal not written | Step 5. Each run pays for model calls: a decision note with the cost comes first. |
| 17 | **Parser comparison, then a targeted second PDF pass** — PaddleOCR, Docling and the current parse on about 200 documents with complex tables or scanned pages; table-aware chunking; the second pass only if it wins. | M | [review](docs/eval/2026-11-23_pkr_testbed_review.md) §8 · proposal not written | Step 6. Independent of rows 13 to 16; can start once row 11 has shipped. Opens C9 and E6. |
| 12 | **Docs: fix the setup path** — services, UI install and env-var docs are wrong; `CLAUDE.md` carries stale banners. | S | [review](docs/eval/2026-11-23_pkr_testbed_review.md) §10 · proposal not written | The destructive snippet was fixed by row 9, shipped 2026-11-23. |
| 1 | **Re-scope the seeding work: measure the *agent* path + `naive_rag`, all 5 anchors** — the step-1 probe measured raw-question retrieval, which the agent never uses; its reformulation already lands the anchor at vector rank 1. Find what is actually broken before building fixes. | S | [`next/tree_retrieval_followups.md`](docs/next/tree_retrieval_followups.md) §1b · [correction](docs/eval/2026-07-20_tree_seeding.md) §6 | **Demoted from `Now` on 2026-11-23:** it tunes the vector path on the seven-page benchmark. Measure after row 11, which changes what the hub pages hold. Gates rows 4–6 and 8 — most of them may turn out unnecessary. |
| 2 | **Ungate `oversample`, then re-baseline the ANN sweep** — `oversample` only applies when a category filter/quota is active, so `neo4j_tree` runs at raw k=10. Survives the re-scope: T5-005's anchor is the true rank-5 chunk yet invisible at k≤100 — an index property, independent of phrasing. | S | [`next/tree_retrieval_followups.md`](docs/next/tree_retrieval_followups.md) §2.1 · [measurement](docs/eval/2026-07-20_tree_seeding.md) | **Demoted from `Now` on 2026-11-23**, as row 1. Small and independently justified. |
| 4 | **Title / short-document boost** — deterministic postprocessor countering the length bias against navigational hub pages. | M | [`next/tree_retrieval_followups.md`](docs/next/tree_retrieval_followups.md) §2.2 | **Gated on row 1** — may be unnecessary if agent reformulation already covers it. Likeliest to matter for `naive_rag`. |
| 5 | **Depth-aware scoring** — use `tree_depth` to prefer the shallower doc among branch siblings. | S | [`next/tree_retrieval_followups.md`](docs/next/tree_retrieval_followups.md) §2.3 | **Gated on row 1.** Re-orders the pool only — cannot fix recall cases alone. |
| 6 | **T5 structural regression fixture** — freeze the expected traversal shape (anchor retrieved, N link-expanded, ancestors present) as an assertion over the chain bundle. | S | [`next/tree_retrieval_followups.md`](docs/next/tree_retrieval_followups.md) §4 | Cheap; doesn't depend on judge scores. Do once rows 1–4 settle. |
| 7 | **`steered_agent` baseline + more hubs + cross-family T2 items + LLM request timeout** — the four topic-subgraph follow-ups. | M | [`next/topic_subgraphs_followups.md`](docs/next/topic_subgraphs_followups.md) | Closes out the topic-subgraph work whose eval critique is already written. |
| 8 | **Anchor-then-expand retrieval mode** — first pass over hub-like docs (fan-out/depth, graph-derived), then expand. | L | [`next/tree_retrieval_followups.md`](docs/next/tree_retrieval_followups.md) §2.4 | Only candidate that structurally fixes "not in the pool at all". Last resort — bigger than rows 4 and 5. |

## Later / Parked (with the reason)

| Task | Parked because | Plan / context |
|---|---|---|
| **`tree_context` agent tool** (jump to a hub by name, enumerate a level) | Deferred by design: if seeding (rows 1 and 4) works, the agent never needs to ask. Revisit only if T5 chains show it *knowing* the hub and unable to reach it. | [`next/tree_retrieval_followups.md`](docs/next/tree_retrieval_followups.md) §3, [`docs/RETRIEVAL.md`](docs/RETRIEVAL.md) §7.2 |
| **Metadata steering** (`doc_type` / `audience` / `site_topic` instead of URL category) | Designed and gated — the labels are already on the graph; only their *use* is deferred. | [`next/metadata_steering.md`](docs/next/metadata_steering.md) |
| **Retrieval-miss detection** (exact-span probe: grounded / in-corpus-not-retrieved / novel) | Designed, gated. Would separate retrieval failures from generation failures. | [`next/retrieval_miss_detection.md`](docs/next/retrieval_miss_detection.md) |
| **GraphRAG vs MCP benchmark** (research program) | Designed, gated — scope exceeds v1. Overlaps with rows 14 and 16; fold it in when they get their proposals. | [`next/graphrag_vs_mcp_benchmark.md`](docs/next/graphrag_vs_mcp_benchmark.md) |
| **Phase 4 — the three ablations** (A evidence filtering, B process rewards, C prompting × model tiers) | Blocked on row 3: an ablation without the lift metric measures nothing. | [`project_roadmap/ABLATIONS.md`](project_roadmap/ABLATIONS.md) |
| **DSPy few-shot bootstrap** (teacher → judge-filter → `BootstrapFewShot`) | Scaffolded in `harness/eval/bootstrap.py`; needs **≥50 rated examples** first. | [`CLAUDE.md`](CLAUDE.md) key decisions |
| **Learned re-ranking from citation feedback** | Needs SME citation-verdict data volume that doesn't exist yet. | [`docs/CITATIONS.md`](docs/CITATIONS.md) |
| **Phase 5 — writeup and release** | End of project. | [`project_roadmap/ROADMAP.md`](project_roadmap/ROADMAP.md) Phase 5 |

## Blocked

| Task | Blocked on |
|---|---|
| *(nothing currently blocked)* | — |

> **Note on pushing (updated 2026-11-23).** Whether `git push` works from **Claude's tool
> environment** depends on the session's SSH setup, not on the machine. On 2026-07-20 it
> failed with `Permission denied (publickey)` because `SSH_AUTH_SOCK` was unset. On
> 2026-11-23 it pushed `develop` (`b8f7216..9d91ca0`). Your own shell always pushes.
> Claude pushes only when you ask, tries once and reports the result. A claim that commits
> are unpushed needs a `git fetch` that succeeded first; without one it is unverifiable.

## Open questions (decide, don't build)

Live entries from [`OPEN_QUESTIONS.md`](OPEN_QUESTIONS.md) — each needs a
decision, then moves to `DECISIONS.md`. A question that blocks a task of the work
unit in progress is a note under [`docs/pm/decisions/`](docs/pm/decisions/README.md)
instead.

| Question | Why it matters |
|---|---|
| Rating granularity: full-answer only, or per-step too? | Shapes the feedback store and the few-shot signal. |
| Similarity threshold for cache display | User-visible behaviour of the semantic cache. |
| Benchmark eval: hardcode `cache: false`, or document as convention? | Eval reproducibility. |
| Max agent steps | Cost/latency ceiling per turn. |
| IDMP concept list for node metadata (TASK-016.5) | Whether the ontology seam gets used at all in v1. |
| Ablation B go/no-go: will B3 (SME step labeling) happen? | Decides whether Phase 4 is three ablations or two. |

---

*Not queues, do not add open work to them: `docs/REQUIREMENTS_REVIEW.md` (F1–F20, all
resolved), the 27 work units from before 2026-11-23 in `.claude/work/`,
`.claude/HISTORY.md` (the done log), and `docs/pm/` (a view of the one work unit in
progress).*
