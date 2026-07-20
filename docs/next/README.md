# docs/next — detailed plans for what gets built next

> **This is a catalogue of plans, not a queue.** Which of these is actually next —
> and what is parked and why — is [`BACKLOG.md`](../../BACKLOG.md) at the repo root.
> A plan here is the *detail* behind a backlog row.

Forward-looking design documents, one file per planned capability. Each plan explains
**why** (the goal it serves), **what already exists** to build on, the **design**, concrete
**implementation steps**, and **open decisions** — detailed enough to execute, readable
enough to review. When a plan lands, its decisions move to `DECISIONS.md`, the how-to
moves to the main `docs/`, and the plan file gains a "landed" banner (kept as history).

| Plan | Status | What it is |
|---|---|---|
| [`closed_book_lift.md`](closed_book_lift.md) | 📋 planned | The closed-book baseline and the **lift** metric — the benchmark's headline number. Doubles as the Phase 2.5 contamination screen. |
| [`topic_subgraphs.md`](topic_subgraphs.md) | 🚧 landed (steps 1–6; eval partial) | Precomputed **topic subgraphs**: a curated hub → its exhaustive member list → a pageable `topic_context` tool. Built and evaluated live 2026-07-13 (T2: `topic_agent` 5.000/5.000 vs `steered_agent` 4.700/4.900; [report](../eval/2026-07-13_topic_subgraphs.md)). |
| [`topic_subgraphs_followups.md`](topic_subgraphs_followups.md) | 📋 planned | Four small follow-ups to the subgraphs work: the `steered_agent` baseline, more hubs, cross-family T2 items, and an LLM request timeout. |
| [`tree_retrieval_followups.md`](tree_retrieval_followups.md) | 🚧 step 1 done | Fix **seeding** for tree-aware retrieval. Step 1 measured it ([report](../eval/2026-07-20_tree_seeding.md)): three distinct problems — one ANN artifact, two scoring, two true recall — and `oversample` is gated off in the tree profile. Step 2 (ungate oversampling → title boost → depth signal → anchor-then-expand) next. |
| [`metadata_steering.md`](metadata_steering.md) | 💡 designed (gated) | Steer retrieval on EMA's own labels (`doc_type` / `audience` / `site_topic`) instead of the coarse URL `category`. The labels are already on the graph; only their *use* is deferred. |
| [`retrieval_miss_detection.md`](retrieval_miss_detection.md) | 💡 designed (gated) | An exact-span probe over the corpus that sorts answer spans into *grounded* / *in-corpus-but-not-retrieved* / *novel* — to separate retrieval failures from generation failures. |
| [`graphrag_vs_mcp_benchmark.md`](graphrag_vs_mcp_benchmark.md) | 💡 designed (gated) | A research program comparing Vector RAG, GraphRAG, and openpharma MCP tools — and testing whether a hybrid of all three is the most robust. |

Candidates without a written plan yet (see `docs/REQUIREMENTS_REVIEW.md` and
`OPEN_QUESTIONS.md`): learned re-ranking from citation feedback (needs data), the ablation
grid (Phase 4), and the DSPy few-shot bootstrap (needs ≥ 50 rated examples).
