# Exploration — retrieval design feedback

Two design questions raised by the user (2026-05-30):

1. Is the legacy FAISS index beneficial for the benchmark case? Collecting the
   questions is good, but why build a *retrieval corpus* from the Q&As? Why not
   ask the benchmark question against the full PG corpus minus the Q&A items?
2. Feedback on the PG link-graph traversal. Doesn't LlamaIndex's recursive
   retriever already do this? Aren't the links needed only to construct the
   `NodeRelationship` graph in LlamaIndex?

This doc records what the code actually does (with file:line evidence) and the
analysis behind the answers. No code was changed.

---

## Evidence map (what is actually built)

### Two retrieval paths, two different result-ID semantics

| | FAISS path (`EMA_RETRIEVER=faiss`, legacy) | PG path (`EMA_RETRIEVER=pgvector`, **default since NARR-028**) |
|---|---|---|
| Module | `harness/embed.py` + `harness/retrieve.py` | `harness/retrieve_pg.py` + `harness/pg/*` |
| Index source | `corpus/corpus.jsonl` (26,251 curated Q&A pairs) | `documents`/`chunks` built from Mongo `parsed_documents` (full body text) |
| Unit indexed | one `TextNode` per Q&A, `id_=qa_id`, text=`"Q: … A: …"` (`embed.py:90-95`) | one chunk of narrative prose, id=`chunk_id` |
| Result tuple id | **`qa_id`** (`retrieve.py:124` `qa_id = node.metadata.get("qa_id", node.node_id)`) | **`chunk_id`** (`retrieve_pg.py:51`) |
| Built from corpus.jsonl? | yes | **no** — `embed_pg.py` has no `corpus.jsonl` reference; PG is narrative-only |

`run_eval.py:38` defaults `EMA_RETRIEVER="pgvector"` and at `:115-122` skips the
FAISS load entirely, building `retrieve_fn` from `build_retrieve_fn_pg`. So the
shipped/default retrieval target is **PG narrative chunks**, not the Q&A FAISS index.

### The eval metric is qa_id-keyed → only meaningful for the FAISS path

`harness/eval_retrieval.py:41` computes
`retrieved_ids = {qa_id for qa_id, _score, _meta in top_k}` and
`recall = |gold_qa_ids ∩ retrieved_ids| / |gold_qa_ids|` (`:51`).

- FAISS path: retrieved ids **are** `qa_id`s → Recall@k/Precision@k work.
- PG path (default): retrieved ids are **`chunk_id`s** → intersection with
  `gold_qa_ids` is **always empty** → Recall@k/Precision@k silently report ~0.
- Only **Citation Accuracy** survives the backend switch — it is URL-keyed
  (`eval_retrieval.py:42,53`, matching on `meta["source_url"]` vs
  `gold_sources[].url`). The docstring (`:9-10`) already states it is
  "independent of qa_id identity." That is the backend-agnostic primitive.

→ Latent bug independent of the design decision: a default `run_eval` over the
benchmark today produces meaningless Recall/Precision. Score retrieval by
document/passage (`gold_sources` URLs, or `gold_qa_ids → source_url → doc_id`),
not by qa_id identity.

### Benchmark ↔ corpus provenance

`benchmark/SCHEMA.md`: each item carries `gold_qa_ids` (into corpus.jsonl) **and**
`gold_sources` = `[{url, page}]`. So the benchmark already has a document-level
gold key (`gold_sources`) that maps cleanly onto PG `documents.source_url`.
corpus.jsonl node text is literally `"Q: {question}\n\nA: {answer}"` — the gold
answer verbatim (`embed.py:77`).

### Link-graph traversal — what's implemented vs documented

Implemented (in repo):
- `corpus/ingestion/link_extractor.py` — the MIGR-007-era extractor.
- `harness/pg/queries.py:177 TRAVERSE_LINKS` — `WITH RECURSIVE` CTE, hop-bounded,
  `l.link_type = ANY(%(link_types)s)` (`:190`).
- `harness/retrieve_pg.py:_expand_via_links` (`:339`) — appends one representative
  chunk per visited doc; only runs when `traversal.mode == "auto"` (`:413`).
- `harness/pg/tools.py:follow_links_tool` (`:87`) — the ReAct `agent_tool` mode.
- Defaults: `_DEFAULT_LINK_TYPES = ("hyperlink", "reference_number")`
  (`retrieve_pg.py:60`, `pg/tools.py:26`). `TraversalConfig.mode` default = `"none"`
  (`retrieve_pg.py:138`).
- `LinkType = Literal["hyperlink", "reference_number", "see_qa"]` (`retrieve_pg.py:59`).

**No LlamaIndex retriever in the PG path.** grep for `RecursiveRetriever` /
`IndexNode` across `harness/`,`corpus/` → **zero** hits outside the legacy FAISS
embed. Workflows rebuild `TextNode`s *from the `(id, score, meta)` tuples*
(`workflows/events.py:32`), so retrieval never emits LlamaIndex nodes-with-
relationships in the first place.

**`NodeRelationship` was never used for cross-refs, even on the FAISS path.**
`embed.py:64`: *"LlamaIndex's NodeRelationship enum lacks a RELATED variant in
this version, so cross-reference traversal is implemented directly via metadata
lookup."* cross_refs live as a metadata list and are walked by a hand-written
`follow_cross_refs` tool.

### ⚠ MIGR-018..025 ("link graph as retrieval cornerstone") is documented but NOT in the repo

DECISIONS.md (lines 255-279) and `docs/RETRIEVAL_PG.md` §14 describe, as **shipped
with operational evidence** (2,279,311 anchors over 22,743 rows, ~6 min wall time,
`file_link` promoted into the default traversal tuple via MIGR-020):
- `corpus/extractors/link_graph.py`, `corpus/sources/link_graph.py`,
  `scripts/backfill_link_graph.py`
- a Mongo `link_graph` collection, `ClassifiedAnchor`, `extract_links`
- `file_link` / `page_link` link types and `file_link` in the default tuple

Verification (2026-05-30):
- `find . -name '*link_graph*'` → **nothing**.
- grep `file_link|page_link|link_graph|ClassifiedAnchor|extract_links` in `*.py`
  → **zero hits**. They appear only in `.md` files (CLAUDE.md, DECISIONS.md,
  HISTORY.md, RETRIEVAL_PG.md, deploy/mongo/README.md) and work-unit notes.
- `git log` stops at MIGR-017 (+ the Mongo-Docker infra commit). No MIGR-018+
  commit; `git status` shows nothing untracked matching link/migr/extractor.
- Live defaults are the **pre-MIGR-020** values (`hyperlink`,`reference_number`);
  `LinkType` Literal does not even list `file_link`/`page_link`.
- `TRAVERSE_LINKS` seeds only `link_type='hyperlink'`/`'reference_number'`
  (`queries.py:232,241`).

So the "cornerstone" framing rests on infrastructure that is not present. What is
present is the CTE + tool over a **sparse** `links` table (the one the
2026-05-27 audit measured as having lost ~96% of HTML→PDF file-links) and it is
**off by default** (`mode: none`).

---

## Q1 — analysis: FAISS-over-Q&A as a benchmark retrieval target

The user's instinct is right, with one refinement about what "minus the Q&A items"
should mean.

**Why FAISS-over-corpus.jsonl is the wrong retrieval target for the benchmark:**
1. *It is not the system you ship.* Runtime is pgvector over narrative chunks
   (default). Measuring retrieval on a Q&A FAISS index measures a retriever that
   isn't in production — and contradicts the very rationale of the pgvector
   migration (DECISIONS.md: "the corpus.jsonl Q&A pairs are a tiny fraction of the
   actual content; the agent needs the full narrative body text").
2. *It maximizes leakage in the worst place.* Node text is the verbatim
   `Q: … A: …`. The benchmark question is a paraphrase of that question; the gold
   answer **is** that answer. Retrieval collapses to trivial self-match (inflated
   Recall@k), and the generator is then handed the literal gold answer as
   "context" — so open-book correctness measures "can you copy the answer we put
   in front of you," which destroys the meaning of **lift** (the headline metric).
3. *The metric is half-broken across backends* (see evidence map): qa_id Recall
   only works on FAISS; on the default PG path it silently reports ~0.

**Refinement on "ask against full PG corpus minus the Q&A items":**
- PG is built from **full documents**, not from corpus.jsonl rows — there are no
  discrete "Q&A items" sitting in PG to subtract. There are full PDFs/HTML pages
  that *contain* the Q&As.
- For standard T1–T3 items, the gold passage being present **is the task, not
  leakage** — open-book retrieval is "can the retriever find the answer-bearing
  passage?" Deleting the source document makes the item unanswerable open-book.
- The two leakage threats are handled elsewhere, not by corpus surgery:
  (a) *curated-gold spoon-feeding* → fixed by retrieving narrative prose instead
  of the curated Q/A surface (already the default once FAISS is dropped);
  (b) *training-data memorization* → fixed by closed-book baseline + lift
  (LEAKAGE.md), not by deleting documents.
- Where a hold-out **is** right: author-written **T4 composite/counterfactual**
  items where you deliberately exclude a source to test synthesis/generalization.
  That is a per-item, intentional hold-out — not a blanket "remove all Q&As."

**Recommendation (Q1):**
1. Make the benchmark retrieval target the PG narrative corpus (already default).
   Demote FAISS-over-corpus.jsonl to an opt-in parity fixture, or retire it from
   the eval critical path.
2. Fix `eval_retrieval` to score retrieval by **document/passage** — use
   `gold_sources` URLs (already present) or map `gold_qa_ids → source_url → doc_id`.
   Promote the URL/doc-level recall (today's Citation Accuracy) to the headline
   retrieval metric; stop relying on qa_id intersection.
3. Keep corpus.jsonl for what it is genuinely good at — source of questions, gold
   answers, `gold_qa_ids` provenance, the `cross_refs` graph for authoring T3
   items, and the closed-book answer key. None of those need a FAISS index.

## Q2 — analysis: link-graph traversal vs LlamaIndex recursive retrieval

**On the mechanism the user assumed — the premise doesn't hold:**
- LlamaIndex `RecursiveRetriever` is **not in the PG path** and has nothing to
  recurse over (retrieval emits tuples, not nodes).
- Even on the FAISS path, `NodeRelationship` was **never** used for cross-refs
  (`embed.py:64`) — traversal has always been manual metadata lookup.
- `RecursiveRetriever` ≠ graph traversal anyway: it follows `IndexNode`
  *references* (small-to-big / route-to-sub-index), not a typed, hop-limited BFS
  over an edge table. The LlamaIndex primitive that *does* graph traversal is
  `PropertyGraphIndex` / a graph store — explicitly **deferred to v2** by
  DECISIONS.md ("No ontology or graph infrastructure in v1").
- So the recursive-CTE traversal is the project's *own* replacement for recursive
  retrieval, made necessary by the pgvector migration removing LlamaIndex's
  retriever. Given that architecture, the CTE (links co-located with vectors,
  one round-trip, hop-bounded, type-filtered) is the *right* tool — closer to what
  the project wants than `RecursiveRetriever` would be.

**On the user's deeper smell — partly right:**
- The "cornerstone" is largely **documented-but-not-built** (see ⚠ above).
- `traversal.mode` defaults to **none**; ablations that would justify it haven't
  run. CLAUDE.md rule: "Every added complexity layer must be justified by a
  specific benchmark failure, not anticipation." The elaborate
  extractor/backfill described in MIGR-018..025 is the exact anticipatory
  complexity the project says it wants to avoid.

**Recommendation (Q2):**
1. Separate *storing* edges (cheap — keep the `links` table + `resolve_links`
   typing; you want it regardless) from *traversing* them at query time (the
   unproven expansion — keep `mode: none` by default until a benchmark failure
   calls for it).
2. Reconcile docs with reality: implement MIGR-018..025, or downgrade DECISIONS.md
   §"Link graph as retrieval cornerstone" and RETRIEVAL_PG.md §14 to
   "planned / not yet shipped" and remove the operational-evidence numbers. They
   currently read as done, which will mislead planning.
3. Do **not** reach for `RecursiveRetriever` / `PropertyGraphIndex` to "do it
   properly" — that re-introduces the index/docstore layer the pgvector migration
   removed and pulls graph infra deferred to v2.
4. When Phase 2 lands, gate traversal behind an ablation (matches ABLATIONS.md
   Ablation B). Measure T3/T4 lift with traversal on vs off — that is the
   justification the project's own rules demand.

---

## Q2 follow-up (user, 2026-05-30): "why reimplement if LlamaIndex does this; the project's purpose was a node graph mirroring the EMA site"

Decisive finding — the pgvector migration didn't just replace LlamaIndex's
*retriever*, it dropped the **node graph itself**. None of the three structures
the user names survive into the retrieval store:

- **Hierarchical sub-nodes discarded at chunk time.** `corpus/ingestion/chunker.py:92`
  (the `hierarchical` branch) builds the `HierarchicalNodeParser` tree, then
  `nodes = [n for n in nodes if not getattr(n, "child_nodes", None)]` — keeps only
  leaves, drops every parent/child edge. `Chunk` dataclass has no relationship
  fields. So AutoMergingRetriever / small-to-big recursive retrieval is impossible
  (nothing to merge up to).
- **`chunks` table is flat** (`pg_schema.sql:52-61`): no `parent_chunk_id`, no
  PREVIOUS/NEXT, only `chunk_index` ordering + `doc_id` FK.
- **`links` table is document-level** (`pg_schema.sql:71-79`): edges are
  `src_doc_id → tgt_doc_id`; `chunk_id` only records where an anchor appeared, not
  a node→node edge.

So the built system is: flat chunk table + doc-level adjacency side-table +
hand-rolled SQL traversal — a *different* architecture from the stated
"LlamaIndex node graph mirroring the EMA site."

**Why (honest):** the NARR decision (DECISIONS.md NARR-001..028) optimized for SQL
prefilters + BM25 + idempotent ingest and listed "link-graph traversal via
recursive CTE" as a *benefit*, without recording that it (a) reimplements a
framework feature already paid for, (b) abandons the node-graph + LlamaIndex's
structural retrievers, and (c) undercuts the prior "LlamaIndex as the RAG
framework" decision for the structural-retrieval part. That trade-off is missing
from the decision record.

**Why not just switch to PropertyGraphIndex:**
- It is the v2-deferred infra (DECISIONS.md "No ontology or graph infrastructure
  in v1" names PropertyGraphIndex/Neo4j; gated on Ablation B). At 115k docs it
  wants a real graph store; `SimplePropertyGraphStore` (in-memory) won't hold it.
- Store-wrapper metadata loss has bitten this codebase before (LangChain
  `EMARetriever` removed for "stripped node metadata"). LlamaIndex `PGVectorStore`
  manages its own table shape — wouldn't give the typed `documents`/`links` model,
  SQL prefilter-before-ranking, or the BM25 generated column for free.
- Middle path (`VectorStoreIndex` over `PGVectorStore`) recovers vector+node +
  AutoMerging, but PropertyGraphIndex is a separate index type — no "pgvector +
  property graph in one store." Still two systems for the graph part.

**Reframe — the decision upstream of build-vs-buy:** at what *granularity* is
structure represented, and is it first-class or a side table? Fix that first:
- If structure is the thesis → represent it at node/chunk granularity (stop
  discarding parents in `chunker.py:92`; add `chunks.parent_chunk_id`; resolve
  `links` to chunks). Postgres recursive CTEs are a legitimate graph engine, so
  the relational store can remain system-of-record; decide LlamaIndex-vs-SQL
  traversal deliberately, with metadata fidelity tested.
- Per "justify by failure": flat-but-correct pgvector baseline → real benchmark →
  measure T2/T3/T4 failures → then invest, gated behind Ablation B.

Recommendation: do **not** migrate to PropertyGraphIndex now; do **not** keep
docs claiming the SQL store realizes the node-graph vision. Reopen NARR as an
explicit written trade-off; fix the granularity question on the relational side
(cheap, unblocks AutoMerging-style retrieval without a graph DB); gate the
framework-vs-SQL traversal choice behind an actual Ablation B result.
New decision: **D5 — reopen/annotate the NARR pgvector decision with the
structural-retrieval trade-off it omitted.**

## Q2 follow-up 2 (user, 2026-05-30): the two LlamaIndex doc patterns

User cited two patterns as ways to mimic the EMA page graph:
(1) `recursive_retriever_nodes` (RecursiveRetriever + IndexNode), and
(2) `knowledge_graph_rag_query_engine` (KnowledgeGraphIndex / KG RAG), "start with
links-to only, extend later." Both links are on the old `gpt-index.readthedocs.io`
site.

Confirmed via context7 against current LlamaIndex docs (lib now v0.14.x):
- **KnowledgeGraphIndex, KnowledgeGraphRAGRetriever, KnowledgeGraphQueryEngine are
  DEPRECATED as of v0.10.53** — explicit "use PropertyGraphIndex instead." So
  pattern (2)'s API is dead; the modern vehicle is `PropertyGraphIndex`.
- **RecursiveRetriever + IndexNode is current.** Mechanism: when a retrieved node
  is an `IndexNode`, it follows `index_id` into the referenced retriever/query
  engine and recurses (dedups repeated index_ids). It is *reference-following /
  small-to-big*, NOT hop-bounded links-graph BFS, and depends on LlamaIndex's
  docstore + object map to resolve `index_id → object`.

Mapping to the EMA structure:
- Pattern (1) ↔ the **hierarchy** half (parent/child sub-nodes). Good fit, but
  impossible on the current store: `chunker.py:92` discards parents → no IndexNodes
  to recurse through; needs LlamaIndex's object map the SQL store bypasses.
- Pattern (2)/PropertyGraphIndex ↔ the **links-to graph** half. Data-model
  instinct ("simple links-to, extend to typed edges later") is sound and is exactly
  PropertyGraphIndex's model. Catch: needs a property graph store —
  `SimplePropertyGraphStore` (in-memory, won't scale to 115k docs / millions of
  anchors) or Neo4j/Nebula/Memgraph (= the v2-deferred graph DB). No pgvector-native
  property-graph store reuses the existing tables.

### The third option the NARR decision skipped (resolves "why reimplement?")
NARR framed it as binary: raw-SQL store vs LlamaIndex indexes. Missed option:
**implement LlamaIndex's `PropertyGraphStore` interface (and/or a thin
`BaseRetriever`) over the existing Postgres tables** — `documents`=nodes,
`links`=`links-to` triplets, recursive CTE = the traversal impl. Then pgvector+SQL
stay the engine (prefilters, BM25, idempotent ingest, typed relational model, no
wrapper metadata-loss risk) AND PropertyGraphIndex's retrievers/query engines +
typed-edge extensibility sit on top — no second DB, no v2 graph infra. Same trick
for hierarchy: keep parent nodes + `chunks.parent_chunk_id` → AutoMerging/recursive
retrieval work. Costs an adapter (more code than dropping in Neo4j) but is the only
path giving both "LlamaIndex node-graph semantics" and "keep the store you built."

Retrieval-framework choice (A re-home under LlamaIndex / b1 SQL CTE / b2 custom
PG-backed store) stays **benchmark-gated** (Ablation B). The non-gated cheap
unblock for all three: stop destroying structure at ingest (keep non-leaf nodes;
`chunks.parent_chunk_id`; chunk-granularity link resolution) so the EMA node-graph
is materialized before the framework choice is made.

New decision: **D6 — if/when structural retrieval is in scope, evaluate a
Postgres-backed `PropertyGraphStore` adapter (b2) before either re-homing under
LlamaIndex indexes (A) or committing to the SQL-only CTE (b1).**

## Open decisions (for the user) — see requirements.md
- D1: Retire the corpus.jsonl FAISS path from eval, or keep as parity-only fixture?
- D2: Fix `eval_retrieval` to document/passage-level scoring now, or defer to Phase 2?
- D3: Implement MIGR-018..025, or mark as not-yet-shipped in the docs?
- D4: Keep link traversal `mode: none` until a measured T3/T4 failure (recommended)?
