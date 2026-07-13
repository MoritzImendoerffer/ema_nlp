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
| [`metadata_steering.md`](metadata_steering.md) | 💡 designed (gated) | Use the **authoritative node metadata** (`doc_type` 96.6% of PDFs / `audience` / `site_topic`, landed 2026-07-12) for steering — ground `category` on `doc_type`, replace the URL-based `veterinary` rule with the badge, route on `site_topic`, doc-type-granular priority; metadata already on the graph, only the *use* waits for a §5 trigger |
| [`graphrag_vs_mcp_benchmark.md`](graphrag_vs_mcp_benchmark.md) | 💡 designed (gated) | **GraphRAG × MCP comparison-and-complementarity program** — four arms (Vector RAG / GraphRAG-Cypher / openpharma MCP / Hybrid) × two benchmark slices (existing process-narrative + new MCP-generated product-safety) × a metric frontier; proves *where each technique wins and that the Hybrid is most robust*, plus an MCP-as-oracle ontology-quality sub-study; phased + gated (§8) |
| [`topic_subgraphs.md`](topic_subgraphs.md) | 🚧 landed (steps 1–6; eval partial) | **Precomputed topic subgraphs** — hub seed list → offline metadata-qualified walk → `topic_hubs` membership stamps → pageable `topic_context` tool under explicit token budgets; **built + evaluated live 2026-07-13**: T2 head-to-head topic_agent 5.000/5.000 vs steered_agent 4.700/4.900 (Opus), cross-type sweep shows no collapse — see [`docs/eval/2026-07-13_topic_subgraphs.md`](../eval/2026-07-13_topic_subgraphs.md) |
| [`topic_subgraphs_followups.md`](topic_subgraphs_followups.md) | 📋 planned | **Subgraph follow-ups** — the `steered_agent` T1/T3/T4 baseline (formal no-regression verdict), more hubs (worksharing first — the sweep's failures concentrate there), 2–3 cross-family T2 items, and a client-side LLM request timeout (the observed 70-min silent eval hang) |

Candidates without a written plan yet (see `docs/REQUIREMENTS_REVIEW.md` +
`OPEN_QUESTIONS.md`): learned re-ranking from
citation feedback (needs data), the ablation grid (Phase 4), DSPy few-shot bootstrap (needs
≥50 rated examples). *(The external-tools/MCP policy surface (R4) now has a written plan —
`graphrag_vs_mcp_benchmark.md`; the graph-navigation tools candidate (R1-Q2) now has one —
`topic_subgraphs.md`.)*
