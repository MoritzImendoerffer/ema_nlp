# Requirements / open decisions — retrieval design feedback

This work unit is an **investigation**, not a feature. It produced design feedback
on two user questions and surfaced one doc/reality drift. No implementation is
committed; the items below are decisions to make before any code lands.

## Decisions to make

### D1 — Benchmark retrieval target
**Question:** Retire the `corpus.jsonl` FAISS path from the benchmark/eval critical
path, or keep it as an opt-in parity fixture only?
**Recommendation:** Retire from the critical path; benchmark retrieval = PG
narrative corpus (already the runtime default). Keep FAISS only if a documented
parity smoke-test still has value.
**Rationale:** FAISS-over-Q&A is not the shipped retriever, maximizes gold-answer
leakage, and breaks the lift metric. (exploration.md §Q1)

### D2 — Fix `eval_retrieval` ID semantics
**Question:** Score retrieval at document/passage level now, or defer to Phase 2?
**Recommendation:** Fix now — it is a latent correctness bug. On the default PG
backend, qa_id-keyed Recall@k/Precision@k report ~0 because retrieved ids are
`chunk_id`s. Use `gold_sources` URLs (present in every item) or map
`gold_qa_ids → source_url → doc_id`. Promote URL/doc-level recall (today's
Citation Accuracy) to the headline retrieval metric.
**Acceptance:** a default `run_eval` over `benchmark.jsonl` produces non-degenerate
Recall/Precision broken down by T1–T4.

### D3 — Reconcile the link-graph docs with reality
**Question:** Implement MIGR-018..025, or mark them not-yet-shipped?
**Finding:** `corpus/extractors/link_graph.py`, `corpus/sources/link_graph.py`,
`scripts/backfill_link_graph.py`, the Mongo `link_graph` collection, and the
`file_link`/`page_link` link types **do not exist in the repo**. DECISIONS.md
(255-279) and RETRIEVAL_PG.md §14 describe them as shipped with operational
metrics. CLAUDE.md's intro also asserts the repair is done.
**Recommendation:** Either implement, or downgrade those sections to
"planned / not yet shipped" and drop the operational-evidence numbers. Do not
leave docs claiming a shipped cornerstone that is absent.

### D4 — Default state of link traversal
**Question:** Keep `traversal.mode: none` by default until a measured failure?
**Recommendation:** Yes. Store edges (cheap, keep), but keep query-time traversal
off by default. Gate it behind an ablation in Phase 2 (ABLATIONS.md Ablation B)
and turn it on only if T3/T4 lift justifies it — per CLAUDE.md's
"justify by failure, not anticipation" rule.

## Non-goals
- No `RecursiveRetriever` / `PropertyGraphIndex` / graph-DB adoption (v2-deferred).
- No deletion of source documents from PG to "decontaminate" (breaks open-book).
- No model training / DSPy (separate deferred decision).

## Next step
Decisions D1–D4 are independent and small. If the user approves any subset,
`/plan` can turn them into ordered tasks (D2 and D3 are the lowest-risk,
highest-value starting points).
