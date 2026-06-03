# Requirements — graph-aware retrieval (LINKS_TO traversal)

## Problem
The chat retriever (`HierarchicalPGRetriever`) does vector search + small-to-big parent
merge, but never traverses `LINKS_TO`. The link graph (1.72M edges) and the profile's
`graph.{max_hops,edge_types}` config are unused at query time — the cornerstone "site
structure as retrieval signal" thesis is not realized. (LIR-008 claimed it; never delivered.)

## Functional requirements
- **FR1** `HierarchicalPGRetriever` performs a bounded 1-hop `LINKS_TO` expansion: from the
  seed hits' documents, follow `LINKS_TO` to neighbour documents and add the **globally
  top-M** most query-relevant neighbour chunks (cosine vs. the query embedding).
- **FR2** Expansion is driven by `profile.retrieval.graph` — `max_hops` (0 ⇒ disabled),
  `edge_types` (currently `links_to`), plus `expand_m` and `link_decay`. `build_hierarchical_retriever`
  passes the graph config through.
- **FR3** Expanded nodes are deduped against direct hits, carry a decayed score
  (`link_decay * sim`), and are attributable: `metadata.via_link=True`,
  `metadata.linked_from=<seed source_url>`. Direct hits are unchanged and still rank first.
- **FR4** Output is additive: up to `k` direct + up to `M` expanded NodeWithScore, all with
  `source_url`/`doc_id` provenance.
- **FR5** Hub blow-up is bounded (per-neighbour top-1 + global LIMIT M), independent of a
  seed doc's out-degree (some hubs link to 500+ docs).

## Non-functional
- **NFR1** No latency regression that breaks the chat — measure on the live graph; cap if needed.
- **NFR2** `max_hops=0` reproduces today's behaviour exactly (clean ablation toggle).
- **NFR3** Works on the real built graph (79,882 docs / 1.72M LINKS_TO), not just fixtures.

## Acceptance criteria
- [ ] With `max_hops>0`, a query whose seed doc has `LINKS_TO` neighbours returns ≥1 node with
      `via_link=True` + `linked_from` set, scored below the direct hits.
- [ ] With `max_hops=0`, results are identical to the pre-change retriever (regression-safe).
- [ ] Unit test (fake store: seed + neighbour chunks) asserts expansion, decay, dedup, M-cap,
      and the disabled path.
- [ ] Live verify on the real graph: show the expansion firing with provenance + plausible
      relevance; record latency.
- [ ] `ruff` + indexing test suite green.

## Secondary (query-cache hygiene — explains "embedded query did nothing")
- **S1** Clear the 15 stale pre-refactor query-cache entries (answers over the deleted corpus).
- **S2** Provide a way to run retrieval without the cache short-circuit for clean testing
  (e.g. `EMA_QUERY_CACHE_DISABLED=1`, or skip the AskAction prompt) — lower priority.

## Out of scope
- Multi-hop (`max_hops>1`) — keep v1 at 1 hop.
- Typed/weighted edges beyond `links_to`.
- LlamaIndex-native RecursiveRetriever/AutoMergingRetriever (custom Cypher per LIR-008 spike).
- Benchmark-driven tuning of M/decay (no benchmark on this branch yet).

## Decision needed (non-blocking; defaults chosen)
- Neighbour-chunk selection: **query-relevant top chunk per neighbour** (recommended) vs. the
  neighbour's root chunk. M=5, link_decay=0.5 defaults. Confirm or adjust.
