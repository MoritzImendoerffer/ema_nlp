# Backlog — the single ranked queue of open work

**This file is the one place that answers "what's open, and what's next."** Every
other document keeps its detail; a row here is the pointer plus the status.

## Rules

1. **Nothing is open unless it has a row here.** Detailed plans live in
   [`docs/next/`](docs/next/README.md), findings in [`docs/eval/`](docs/eval/),
   decisions in [`DECISIONS.md`](DECISIONS.md). A row links out; it never
   duplicates the content.
2. **`Now` is capped at 3.** A fourth item cannot start until one finishes or is
   explicitly demoted to `Next`. This cap is the point of the file — it forces
   the "what about the other thing?" question at planning time.
3. **Closing is one move:** delete the row, append a line to
   [`.claude/HISTORY.md`](.claude/HISTORY.md). Do it in the same commit as the
   code.
4. **Phase status stays in** [`project_roadmap/ROADMAP.md`](project_roadmap/ROADMAP.md);
   item status stays here. The roadmap links here rather than restating.

Sizes: **S** ≈ one session · **M** ≈ a few sessions · **L** ≈ a week+.

---

## Now (max 3)

| # | Task | Size | Plan / context | Notes |
|---|---|---|---|---|
| 1 | **Ungate `oversample`, then re-baseline the ANN sweep** — `oversample` only applies when a category filter/quota is active, so `neo4j_tree` runs at raw k=10 and loses near-top-ranked hubs. | S | [`next/tree_retrieval_followups.md`](docs/next/tree_retrieval_followups.md) §2.1 · [measurement](docs/eval/2026-07-20_tree_seeding.md) | Fixes T5-005 outright; re-baselines every other rank in the report. |
| 2 | **Closed-book baseline + lift metric** — the benchmark's headline number, and the Phase 2.5 contamination screen. | L | [`next/closed_book_lift.md`](docs/next/closed_book_lift.md) | Blocks the Phase 3 exit criteria and any honest ablation result. |
| 3 | *(free slot)* | | | Keep one slot open, or promote from `Next`. |

## Next (ordered)

| # | Task | Size | Plan / context | Notes |
|---|---|---|---|---|
| 4 | **Title / short-document boost** — deterministic postprocessor countering the measured length bias against navigational hub pages. | M | [`next/tree_retrieval_followups.md`](docs/next/tree_retrieval_followups.md) §2.2 | Targets the 2 scoring + 2 recall anchors that oversampling can't reach. Do after #1 re-baselines. |
| 5 | **Depth-aware scoring** — use `tree_depth` to prefer the shallower doc among branch siblings. | S | [`next/tree_retrieval_followups.md`](docs/next/tree_retrieval_followups.md) §2.3 | Re-orders the pool only — cannot fix the recall cases alone. Combine with #4. |
| 6 | **T5 structural regression fixture** — freeze the expected traversal shape (anchor retrieved, N link-expanded, ancestors present) as an assertion over the chain bundle. | S | [`next/tree_retrieval_followups.md`](docs/next/tree_retrieval_followups.md) §4 | Cheap; doesn't depend on judge scores. Do once #1–#4 settle. |
| 7 | **`steered_agent` baseline + more hubs + cross-family T2 items + LLM request timeout** — the four topic-subgraph follow-ups. | M | [`next/topic_subgraphs_followups.md`](docs/next/topic_subgraphs_followups.md) | Closes out the topic-subgraph work whose eval critique is already written. |
| 8 | **Anchor-then-expand retrieval mode** — first pass over hub-like docs (fan-out/depth, graph-derived), then expand. | L | [`next/tree_retrieval_followups.md`](docs/next/tree_retrieval_followups.md) §2.4 | Only candidate that structurally fixes "not in the pool at all". Last resort — bigger than #4/#5. |

## Later / Parked (with the reason)

| Task | Parked because | Plan / context |
|---|---|---|
| **`tree_context` agent tool** (jump to a hub by name, enumerate a level) | Deferred by design: if seeding (#1/#4) works, the agent never needs to ask. Revisit only if T5 chains show it *knowing* the hub and unable to reach it. | [`next/tree_retrieval_followups.md`](docs/next/tree_retrieval_followups.md) §3, [`docs/RETRIEVAL.md`](docs/RETRIEVAL.md) §7.2 |
| **Metadata steering** (`doc_type` / `audience` / `site_topic` instead of URL category) | Designed and gated — the labels are already on the graph; only their *use* is deferred. | [`next/metadata_steering.md`](docs/next/metadata_steering.md) |
| **Retrieval-miss detection** (exact-span probe: grounded / in-corpus-not-retrieved / novel) | Designed, gated. Would separate retrieval failures from generation failures. | [`next/retrieval_miss_detection.md`](docs/next/retrieval_miss_detection.md) |
| **GraphRAG vs MCP benchmark** (research program) | Designed, gated — scope exceeds v1. | [`next/graphrag_vs_mcp_benchmark.md`](docs/next/graphrag_vs_mcp_benchmark.md) |
| **Phase 4 — the three ablations** (A evidence filtering, B process rewards, C prompting × model tiers) | Blocked on #2: an ablation without the lift metric measures nothing. | [`project_roadmap/ABLATIONS.md`](project_roadmap/ABLATIONS.md) |
| **DSPy few-shot bootstrap** (teacher → judge-filter → `BootstrapFewShot`) | Scaffolded in `harness/eval/bootstrap.py`; needs **≥50 rated examples** first. | [`CLAUDE.md`](CLAUDE.md) key decisions |
| **Learned re-ranking from citation feedback** | Needs SME citation-verdict data volume that doesn't exist yet. | [`docs/CITATIONS.md`](docs/CITATIONS.md) |
| **Phase 5 — writeup and release** | End of project. | [`project_roadmap/ROADMAP.md`](project_roadmap/ROADMAP.md) Phase 5 |

## Blocked

| Task | Blocked on |
|---|---|
| Push commits to `origin` | No git credentials on marvin-gpu (`Permission denied (publickey)`). Commit locally; push from a credentialed machine. Currently **8 unpushed commits** on `develop`. |

## Open questions (decide, don't build)

Live entries from [`OPEN_QUESTIONS.md`](OPEN_QUESTIONS.md) — each needs a
decision, then moves to `DECISIONS.md`:

| Question | Why it matters |
|---|---|
| Rating granularity: full-answer only, or per-step too? | Shapes the feedback store and the few-shot signal. |
| Similarity threshold for cache display | User-visible behaviour of the semantic cache. |
| Benchmark eval: hardcode `cache: false`, or document as convention? | Eval reproducibility. |
| LLM judge model choice | Affects every eval number; currently Anthropic-only by construction. |
| Max agent steps | Cost/latency ceiling per turn. |
| IDMP concept list for node metadata (TASK-016.5) | Whether the ontology seam gets used at all in v1. |
| Ablation B go/no-go: will B3 (SME step labeling) happen? | Decides whether Phase 4 is three ablations or two. |

---

*Historical trackers (do not add to these): `docs/REQUIREMENTS_REVIEW.md`
(F1–F20, all resolved), `.claude/work/` (per-work-unit docs),
`.claude/HISTORY.md` (the done log).*
