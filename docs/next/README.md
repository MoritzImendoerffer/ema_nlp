# docs/next — detailed plans for what gets built next

Forward-looking design documents, one file per planned capability. Each plan explains
**why** (the goal it serves), **what already exists** to build on, the **design**, concrete
**implementation steps**, and **open decisions** — detailed enough to execute, readable
enough to review. When a plan lands, its decisions move to `DECISIONS.md`, the how-to
moves to the main `docs/`, and the plan file gains a "landed" banner (kept as history).

| Plan | Status | One-liner |
|---|---|---|
| [`closed_book_lift.md`](closed_book_lift.md) | 📋 planned | Closed-book baseline + the **lift** metric — the benchmark's headline number, and the Phase 2.5 contamination screen it doubles as |
| [`retrieval_miss_detection.md`](retrieval_miss_detection.md) | 💡 designed (gated) | OLMoTrace-style exact-span probe (infini-gram) over the corpus — buckets answer spans into grounded / **in-corpus-but-not-retrieved** / novel for eval triage, memorization signature, citation repair; build waits for a §5 trigger |

Candidates without a written plan yet (see `docs/REQUIREMENTS_REVIEW.md` +
`OPEN_QUESTIONS.md`): graph-navigation tools for the agent (R1-Q2), external tools/MCP
policy surface (R4), learned re-ranking from citation feedback (needs data), the ablation
grid (Phase 4), DSPy few-shot bootstrap (needs ≥50 rated examples).
