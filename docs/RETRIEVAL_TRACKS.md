> ⚠️ **STATUS: UNIMPLEMENTED PROPOSAL (superseded).** This is a 2026-06-04 design spec, not
> shipped code. Only its **prerequisite P1** (the link-extraction upgrade, work unit 24) was
> built; **Tracks A/B/C and the comparison harness were never implemented**, and
> `GraphRetrievalConfig`'s `max_hops`/`edge_types` remain parsed-but-unconsumed. Its **§4
> comparison harness is wired around Arize Phoenix, which was fully removed on 2026-06-22** in
> favour of MLflow — that section's tracing approach and `app.py`/`utils.py` line refs are dead.
> The project's direction has since moved to the **agent-centric recipe engine**
> ([`RECIPES.md`](RECIPES.md), [`RAG_TECHNIQUES.md`](RAG_TECHNIQUES.md)); the native-retriever
> ideas here survive only as the reserved (unwired) `harness/retrieval/native_pg.py` seam. Kept
> for its adversarial LlamaIndex/Neo4j findings, which remain accurate.

# Retrieval tracks — three retrievers over the existing ingest seam

Spec for **three new retrieval tracks** plus the **comparison harness** that grades them, all
registered through the existing `INDEX_REGISTRY` / `RETRIEVER_REGISTRY` + `EMA_INDEX_PROFILE`
seam (`harness/indexing/`). Style follows `HARNESS_REFACTORS.md` (since deleted):
per-change Problem / Approach / Files / Profile-schema / Decision points (with a recommendation) /
Test plan / Acceptance / Effort / Open questions.

> **Status: spec only — no code until reviewed.** This document is the deliverable. It was produced
> by a verify→design→adversarially-review pass (each track's risky LlamaIndex/Neo4j claims were
> checked against the *installed* package source before the design was drafted, then the design was
> reviewed against the ground rules and the live system). The **Review-driven corrections** callouts
> per track record what the adversarial pass changed from the first draft — they are the highest-signal
> part of this spec, not boilerplate.

Authoritative where docs disagree: `CLAUDE.md`. The `docs/RETRIEVAL.md` status box is stale (it says
the build is a CPU subset; **the full graph is live on this host** — see §0.3).

---

## 0. Shared context, ground rules, and one shared prerequisite

### 0.1 The one ingestion path (every track consumes this — no track gets its own Mongo reader)

```
parsed_documents (Mongo)  ──ingest(profile)──▶  list[IngestedDoc]        # harness/indexing/ingest.py
  web_items.html_raw      ──extract_links()──▶  IngestedDoc.links        # harness/indexing/links.py
```

`IngestedDoc` = `doc_id=sha256(url)`, `source_url`, `source_type` (`pdf|html|unknown`), `title`,
`metadata{committee,topic_path,reference_number,…}`, `chunk_nodes` (hierarchical TextNodes, **all
levels**, leaves flagged `is_leaf=True`, deterministic 32-hex ids), `links` (`ExtractedLink{tgt_url,
anchor, kind∈{file,page,external}, tgt_doc_id}`). `corpus.jsonl` is **benchmark-only and never
indexed** (leakage lock).

### 0.2 The one switching mechanism (do not invent a second)

`@register_index(kind)` / `@register_retriever(strategy)` in `harness/indexing/registry.py`;
`build_index(profile)` dispatches on `profile.index.kind`, `build_retriever(profile, index)` on
`profile.retrieval.strategy`. Builders self-register when their module is imported by
`harness/indexing/__init__.py`. The active profile is `harness/configs/index/<name>.yaml`, selected by
`EMA_INDEX_PROFILE`. A new track = **one index kind + one retriever strategy + one profile YAML**;
workflows / Chainlit / Phoenix are untouched (they consume a `BaseRetriever` via
`get_workflow(name, retriever=…, llm=…)`).

### 0.3 Live system facts (verified on this host, 2026-06-04 — not a subset)

| Fact | Value | Consequence |
|------|-------|-------------|
| Graph size | 79,882 `:Document`, 7,435,393 `:Chunk` (**5,817,230 leaf-embedded**) | full build is queryable now |
| Edges | `HAS_CHUNK` 7,435,393 · `PARENT_OF` 7,114,468 · `LINKS_TO` 1,721,581 | Track B has real edges to walk |
| Vector indexes | `ema_chunk_embedding` (`:Chunk.embedding`, cosine) **ONLINE**; `entity` (`:__Entity__.embedding`) **ONLINE but UNEMBEDDED** | Track C's "native `VectorContextRetriever` seeds on `__Entity__`" pitfall is **live**, not theoretical |
| Embeddings | BGE-large 1024-d, **L2-normalized on write** (sampled norm = 1.000) | `IndexFlatIP` ≡ cosine for Track A |
| `is_leaf` ⇔ embedded | `c.embedding IS NOT NULL` and `c.is_leaf=true` are **exactly equivalent** (5,817,230 each; zero exceptions) | Track A can key on either predicate |
| Eval suite | `run_eval.py` / `harness/eval*` / `metrics*` **archived** off-branch | the comparison harness must stand alone |

### 0.4 LINKS_TO hygiene — the empirical finding that makes Track B's filter load-bearing

Raw `LINKS_TO` is ~95 % boilerplate:

- The top-100 in-degree targets absorb **1,628,398 / 1,721,581 = 94.6 %** of all edges. They are global
  header/footer nav — *Contacts, Fees payable, Accessibility, Careers, Cookies, Legal notice, FAQ* …
  each with **exactly 21,956** incoming edges (present on ~every page).
- In-degree distribution is power-law: min 0, **p50 1, p90 2, p99 11**, max 21,956, mean 21.5.
- Only **57,993 (3.4 %)** edges point to PDF targets — the HTML→PDF "card" links, which are the actual
  signal, are a tiny minority.
- The `LINKS_TO` **edge carries no `kind` property** (the `file/page/external` class from `ExtractedLink`
  is dropped in `to_graph`). The target's `source_type` (`pdf|html`) **is** on the `:Document` node.

⇒ A retriever that naively follows `LINKS_TO` drowns. **This is fixed structurally, at extraction time, by
prerequisite P1 (§0.8)** — `links.py` parses anchors over the *whole* page, so chrome becomes edges;
scoping to `<main class="main-content-wrapper">` removes the 74 chrome targets that absorb 94.4 % of edges.
The first draft's Track-B `is_nav_hub` degree-cap is **demoted to a secondary safety-net** once P1 lands.

### 0.5 Shared ground rules (every track honors)

1. One ingestion path (consume `ingest()`/`extract_links`; no new Mongo reader).
2. One switching mechanism (registry + profile YAML + `EMA_INDEX_PROFILE`).
3. Never index `corpus.jsonl` (leakage).
4. No restoring pgvector/SQL retrieval (pre-refactor stack is reference-only).
5. Non-goals: **no LLM entity/triplet extraction over the corpus; no agentic/multi-step retrieval; no doc
   edits as a substitute for implementation.**

### 0.6 The shared retriever output contract (new — formalized here)

The comparison harness (§4) grades on **owning-document provenance**, and link tracks need to distinguish
seed from expansion. So every retriever in every track **must** stamp, on each returned
`TextNode.metadata`:

- `source_url` and `doc_id` — the benchmark gold key (the baseline already stamps these,
  `property_graph.py:473–477`);
- `retrieval_origin ∈ {"seed","parent","links_to"}` — provenance for the link-track fairness metric.
  Absent ⇒ treated as `"seed"`; `"parent"` (baseline small-to-big merge) **folds into the seed bucket**
  so a merged parent is never miscounted as expansion.

This contract is documented once in `docs/RETRIEVAL.md` and asserted by the harness's per-run diagnostic
(§4, count of nodes with both `source_url` and `doc_id` null → loud, not silently-zero recall).

### 0.7 Prerequisite P0 — registry-level `open` dispatch (a shared gap Track A surfaced)

**Problem.** Workflows and the UI open the index with a **hardcoded**
`from harness.indexing.property_graph import open_index` (`crag.py`, `react_native.py`, `simple_rag.py`,
`workflows/registry.py`, `app.py`). `open_index` is *not* registry-dispatched — it always opens a Neo4j
`PropertyGraphIndex`. So `EMA_INDEX_PROFILE=vector_flat` (Track A) or `=pg_native_subgraph` (Track C)
would still open a Neo4j graph and hand it to a FAISS/native retriever → crash or silent wrong-store
retrieval. The registry has `build_*` dispatch but **no `open` dispatch**.

**Approach.** Add an `OPEN_BUILDERS` dict + `@register_open(kind)` decorator to `registry.py` and a
`open_index(profile)` dispatcher that routes on `profile.index.kind`; register the existing Neo4j opener
under `property_graph`, and each new track registers its own opener. Rewire the 5 hardcoded call sites to
`from harness.indexing import open_index` (registry dispatch). This is **~30 min, touches 6 files**, and
is a prerequisite for Tracks A and C (Track B reuses the live Neo4j graph, so it works through the
existing `property_graph` opener unchanged).

**Files:** `harness/indexing/registry.py` (+`OPEN_BUILDERS`, `register_open`, `open_index`),
`harness/indexing/__init__.py` (export `open_index`), `harness/indexing/property_graph.py`
(`@register_open("property_graph")` on the existing `open_index`, renamed to a track-local function),
`harness/workflows/{crag,react_native,simple_rag,registry}.py` + `app.py` (swap the import). **Test:**
`test_open_dispatch_routes_on_kind` (register a fake opener, assert dispatch) +
`test_open_unknown_kind_raises`.

> This is listed as P0 because the "needs-revision" verdict on Track A traced directly to it: the
> first Track-A draft claimed "no workflow/UI files change," which is false. Doing P0 once unblocks every
> non-Neo4j track cleanly.

### 0.8 Prerequisite P1 — link-extraction upgrade (supersedes the §0.4 hygiene audit)

> **Work unit [`2026-06-04_24_link-extraction-upgrade`](../.claude/work/2026-06-04_24_link-extraction-upgrade/).**
> Runs **before Track B**; **Track C inherits it via the IR**. It replaces the §0.4 degree-cap *workaround*
> with a *structural* fix: clean, typed `LINKS_TO` edges produced at extraction time.

**Problem.** `harness/indexing/links.py:extract_links()` parses every `<a href>` over the **whole page** and
classifies targets by **URL shape only** (`file/page/external`), discarding DOM context. So global
header/footer/mega-menu chrome becomes `LINKS_TO` edges (§0.4: 74 chrome targets absorb **94.4 %** of
1.72 M edges), and the high-value EMA HTML→PDF "card" links are indistinguishable from inline references.

**The proven extractor to port (not import).** `../ema_scraper/parsers/ema_parser.py` (`EmaPageParser`)
already solves this for the scraper: it scopes to `soup.find("main", class_="main-content-wrapper")`, skips
`bcl-inpage-navigation`/`breadcrumb`/`dropdown-menu`/`<nav>` + `script/style/…`, and is **BCL-component-
aware** — `bcl-file` cards expose `data-ema-document-type`, reference number, and file format. Verified on
the live `web_items.html_raw` (the 22,743-page link source): **40/40 sampled pages have
`main.main-content-wrapper`**, scoping keeps only **36.7 %** of anchors (the rest is chrome), and **21/40**
pages carry `bcl-file` cards. **Caveat:** the scraper's `Link` dataclass stores only `text`+`href` — the
component method *knows* the context but never records it, so the port must **stamp context at each
extraction call site** (`bcl-file`→`file_component`+`document_type`; card/listing/banner→`card_or_listing`;
paragraph/heading/list/table/etc.→`inline`).

**Approach (4 steps).**
1. **Quantify first** *(done — §0.4 + the work unit)*: 1,721,581 edges / 21,957 source pages / 61,114
   targets; **74 targets >5 % of pages absorb 94.4 %**; content remainder ≈ **96,837 edges**.
2. **Port into `links.py`.** Add main-content scoping + `_should_skip` + component dispatch; extend
   `ExtractedLink` with `link_context ∈ {file_component, inline, card_or_listing, other}` and
   `document_type: str | None`. **Keep `tgt_url`, `anchor`, `kind`, `tgt_doc_id` and the existing
   `urljoin`/fragment-strip/`http`-only/self-ref/dedup/`_classify` pipeline unchanged** — every discovered
   `(href, context, document_type)` flows through *our* normalization, not the scraper's raw href. Dedup
   keeps the richest context (`file_component`>`card_or_listing`>`inline`>`other`). No cross-repo import.
3. **Edge model — single `LINKS_TO` label + properties** (`kind, link_context, document_type, anchor`)
   *(recommended over typed labels — see the work unit's exploration §3)*. `to_graph` emits
   `Relation(label="LINKS_TO", properties=…)`; `_merge_links_batch` MERGEs then `SET e += $props`.
   `graph.edge_types` **generalizes to a `link_context` whitelist** (back-compat default
   `[file_component, card_or_listing, inline]`), with an optional `graph.document_types` predicate.
4. **Rebuild edges only.** Batched `DELETE` of `LINKS_TO` (`CALL { … } IN TRANSACTIONS` / apoc) + re-MERGE
   over the 22,743 `html_raw` pages with the new extractor (reusing `ensure_document_id_index`), **touching
   no `:Chunk`/`HAS_CHUNK`/`PARENT_OF`/embeddings** (assert counts unchanged before/after; no GPU,
   ~minutes). Then re-measure §0.4 and verify the 94.4 % concentration is gone (target ≈ 10⁵ edges, max
   target in-degree ≤ ~5 % of pages).

> **Result — executed 2026-06-04 (work unit `2026-06-04_24`).** `LINKS_TO` **1,721,581 → 99,520** (−94.2 %)
> in ~8.5 min, **chunks/`HAS_CHUNK`/`PARENT_OF` byte-for-byte unchanged**. **Zero** chrome targets remain
> (max in-degree **21,956 → 567**, mean 21.5 → 1.25; no target exceeds 5 % of the 20,147 source pages).
> Edges are typed: `file_component` 54,347 (all carry `document_type`) / `inline` 35,673 / `other` 7,865 /
> `card_or_listing` 1,635. The HTML→PDF card signal went from **3.4 % → 58.3 %** of edges (57,992 PDF-target
> edges preserved; the 1.66 M chrome edges that drowned them are gone). **P1 shipped.**

**Files:** `harness/indexing/links.py` (the port), `harness/indexing/property_graph.py` (`to_graph` props +
`_links_pass`/`_merge_links_batch` SET + delete-first), `harness/indexing/profiles.py`
(`GraphRetrievalConfig.edge_types` reinterpretation + optional `document_types`),
`tests/test_indexing_links.py` (fixtures). **Callers unaffected:**
`scripts/backfill_parsed_documents_subset.py` filters on `link.kind == "file"`, which is preserved.

**Decision points (full trade-offs in the work unit):** D3 edge model = **single label + properties**;
D4 `main`-less page = **strict empty + diagnostic count** (quantify main-presence across all 22,743 pages
first); D5 dedup = **richest context wins**.

---

## 1. Track A — `vector_flat`: the control arm

> **Verdict: needs-revision → corrections folded in below.** A plain `VectorStoreIndex` over the **same
> leaf chunks** the `property_graph` path embeds, so A vs `hierarchical` vs B vs C differ *only in
> retrieval*, never in chunking. The fast reference solution and the control arm of every eval.

### Problem

Every retrieval result on this branch couples three independently-variable choices: where vectors live
(Neo4j), what the query does (vector hit → Cypher graph walk for small-to-big merge), and the chunking
(`HierarchicalNodeParser([2048,512,128])`). The eval matrix needs a **control** that holds chunking
constant and strips everything graph-shaped: plain dense top-k over the same leaf embeddings — no parent
merge, no `LINKS_TO`, no Cypher. It is also the obvious "simplest RAG that works here," openable in
seconds from a single FAISS file with no live Neo4j.

### Approach

- **Index kind `vector_flat`** — a stock LlamaIndex `VectorStoreIndex` backed by `FaissVectorStore`
  (vectors; `stores_text=False`) + a `SimpleDocumentStore` (leaf text + `{source_url,doc_id}` metadata),
  persisted via `StorageContext.persist(persist_dir)`.
- **Retriever strategy `vector`** — stock `index.as_retriever(similarity_top_k=k)` (`VectorIndexRetriever`).
  No custom class, no merge, no graph hop. Returns `NodeWithScore[TextNode]` with `source_url`/`doc_id`
  metadata (stamps `retrieval_origin="seed"` per §0.6).
- **Embedding sharing — do not pay BGE twice.** The 5.82 M leaf embeddings already exist on
  `:Chunk(embedding)`. The builder **pulls** them and attaches them to reconstructed `TextNode`s, then
  builds the index under `MockEmbedding(embed_dim=1024)` so `embed_nodes()` short-circuits the model
  (it skips embedding any node whose `.embedding is not None` — verified at
  `llama_index/core/indices/utils.py:embed_nodes`). Net cost ≈ one Bolt scan, **zero GPU**, and the
  embeddings are *byte-identical* to the seed used by `hierarchical` (the cleanest possible control).

> **⚠ Review-driven correction #1 (was a silent-garbage bug).** The first draft pulled via
> `neo4j_store_from_env().structured_query("… RETURN c.embedding …")`. **That returns empty embeddings:**
> `Neo4jPropertyGraphStore.structured_query` applies `value_sanitize()` by default
> (`sanitize_query_output=True`), which **drops any list property with ≥128 elements**
> (`llama_index/core/graph_stores/utils.py`, `LIST_LIMIT=128`). The 1024-d vector is silently stripped
> from every row → every `TextNode` gets `embedding=None` → `MockEmbedding` fills constant dummy vectors
> → a FAISS index of garbage **that raises nowhere**, and a `_FakeStore` unit test would pass while the
> live path is broken. **Fix:** read the embeddings via a **raw `neo4j.GraphDatabase.driver` session**
> (verified to return the full 1024-d list), *or* construct a dedicated `Neo4jPropertyGraphStore(...,
> sanitize_query_output=False)` for the pull only. Add a **build-time assertion** that every
> `node.embedding` is a list of length `dims` before constructing FAISS (fail loud if a dummy slips
> through), and a test that exercises the real read path (not a `_FakeStore` double, which cannot
> reproduce `value_sanitize`).

> **Review-driven correction #2.** Two "open questions" from the first draft are **resolved by
> measurement**: embeddings **are** L2-normalized (norm = 1.000 → `IndexFlatIP` ≡ cosine, correct as
> written), and `c.embedding IS NOT NULL` ≡ `c.is_leaf=true` (5,817,230 each, zero exceptions → key the
> pull on `WHERE c.embedding IS NOT NULL`, which avoids depending on the `is_leaf` property). They are no
> longer open.

A `source` switch keeps the builder honest as a control even with Neo4j down: `embed_source: neo4j`
(default — pull, raw driver) vs `embed_source: ingest` (re-embed leaves from `ingest(profile)` via real
BGE — slow/GPU, no Neo4j; used for CI-scale subsets **and** as the leaf-set equality check). Both paths
converge on the same `VectorStoreIndex`.

### New + touched files

**New:** `harness/indexing/vector_flat.py` — `leaf_nodes_from_neo4j(*, dims, scope)` (raw-driver pull +
length assert), `leaf_nodes_from_ingest(profile)` (fallback: `leaf_nodes(ingest(...)→chunk_nodes)` → 
`TextNode`s), `@register_index("vector_flat") build_vector_flat_index(profile, *, reset=False, …)`
(load-if-present-else-build; `FaissVectorStore(faiss.IndexFlatIP(dims))` + `StorageContext` + persist),
`@register_open("vector_flat") open_vector_flat_index(profile)` (per **P0**;
`load_index_from_storage(StorageContext.from_defaults(vector_store=FaissVectorStore.from_persist_dir(d),
persist_dir=d))`), `@register_retriever("vector") build_vector_retriever(profile, index)`. ·
`harness/configs/index/vector_flat.yaml`. · `tests/test_indexing_vector_flat.py`.

**Touched:** `harness/indexing/__init__.py` (import `vector_flat` so decorators fire);
`harness/indexing/profiles.py` (new `StoreConfig.vector`/`persist_dir`, `IndexConfig.embed_source`);
`docs/RETRIEVAL.md` (add the kind/strategy rows). `harness/index/*` is already git-ignored (`.gitkeep`
exception) — `persist_dir` lands under it, **no `.gitignore` edit needed** (correction #3).

### Profile-schema changes

```python
@dataclass
class StoreConfig:
    graph: str = "neo4j"
    vector: str = "faiss"           # NEW: "faiss" | "simple" (vector_flat only)
    persist_dir: str | None = None  # NEW: FAISS+docstore home; None -> builder default

@dataclass
class IndexConfig:
    kind: str = "property_graph"
    # …existing…
    embed_source: str = "neo4j"     # NEW: "neo4j" (pull, raw driver) | "ingest" (re-embed leaves)
```

Default `persist_dir` = `Path(__file__).resolve().parents[2] / "harness/index/vector_flat"` — **anchor to
the repo root explicitly** (correction #4: `profiles.py` has no repo-root anchor today, and relative paths
must not resolve against CWD or the `results/` Nextcloud symlink). `neo4j_hier.yaml` omits all three new
keys → defaults are ignored by the `property_graph` builder → **behavior byte-for-byte unchanged**.

### Decision points

| # | Decision | Options (trade-off) | **Recommended** |
|---|----------|---------------------|-----------------|
| a | Vector store | FAISS (`IndexFlatIP(1024)`, ~22 GB, SIMD, needs docstore) · SimpleVectorStore (one JSON, ~60 GB, pure-Python O(n·d)) | **FAISS** at scale; `store.vector: simple` selectable for tiny CI fixtures |
| b | Persist layout | under `results/` (a Nextcloud symlink — wrong) · configurable `persist_dir` default `harness/index/vector_flat/` | **`persist_dir`**, default beside `query_cache.faiss`; layout `default__{vector_store,docstore.json,index_store.json}` |
| c | Embedding source | re-embed via `ingest` (correct, Neo4j-free, ~10–12 GPU-h + GSP-crash risk) · pull from Neo4j (zero GPU, byte-identical to seed, **needs raw driver per correction #1**) · persist-during-PG-build (couples kinds) | **pull (`embed_source: neo4j`, raw driver + length assert)** default; `ingest` as the Neo4j-free fallback **and** the leaf-set equality check. Reject persist-during-PG-build (breaks one-builder-per-kind) |

### Test plan (`tests/test_indexing_vector_flat.py`; mirror `test_indexing_property_graph.py`)

`test_profile_loads_vector_flat_defaults` · `test_registered_kind_strategy_and_open` (incl. P0 open
dispatch) · `test_leaf_nodes_from_ingest_uses_leaf_helper` (mongomock, one large doc → exactly the
`is_leaf` nodes, no parent leaks) · `test_build_persists_and_reopens` (≤20 nodes with pre-set 8-d
embeddings, `IndexFlatIP(8)`, `MockEmbedding(8)`; persist → `open_vector_flat_index` → retrieve returns
`source_url`/`doc_id`) · `test_no_reembed_when_embeddings_present` (`_CountingEmbed`; 0 real-embed calls)
· `test_corpus_jsonl_never_read` (grep-style + mongomock with only `parsed_documents`). **Plus a real
Neo4j-read-path test** (correction #1): assert the builder pulls through a sanitize-free path / that the
embedding column survives — *not* a `_FakeStore` double, which can't reproduce `value_sanitize`. Gate it
like the existing live-infra integration checks if it needs Neo4j.

### Acceptance

`EMA_INDEX_PROFILE=vector_flat` builds a persisted FAISS+docstore; `open_vector_flat_index` reopens with
**no Neo4j, no GPU**; `retrieve(q)` yields `source_url`/`doc_id`-stamped nodes. **Required equality test:**
`embed_source:ingest` leaf ids == `leaf_nodes(...)` ids == Neo4j `:Chunk{is_leaf}` ids (the only guard that
A and `hierarchical` truly share leaves). With `embed_source:neo4j`, zero real-embed calls and a
length-asserted FAISS index (no dummy vectors). `corpus.jsonl` never opened. `neo4j_hier` unchanged.
`pytest` / `ruff` / `mypy` green; no live infra in CI except the gated Neo4j-read test.

### Estimated effort

**~2 evenings** (+P0 ~30 min). E1: `profiles.py` fields + YAML + offline tests. E2: `vector_flat.py`
builder/retriever, raw-driver pull + assert, persist/reopen, `__init__` + P0 wiring, one live full-scale
FAISS build from the Neo4j pull (~tens of min, zero GPU).

---

## 2. Track B — `hierarchical_links`: walk the link graph (close the dead-config gap)

> **Verdict: solid → minor corrections folded in.** New registered strategy `hierarchical_links`; does
> **not** mutate `hierarchical` (the unexpanded baseline stays for A/B comparison). Vector seed →
> `LINKS_TO` expansion at the `:Document` level → evidence from linked docs → dedup → cap → provenance.
> Implements `graph.max_hops` / `graph.edge_types`, today parsed but **consumed by nothing**.

### Problem

The link graph is the project's declared retrieval cornerstone — an EMA landing page links to the PDF
that answers the question — but **no retriever walks it**. `HierarchicalPGRetriever._QUERY` seeds on the
chunk vector index, then expands only `HAS_CHUNK` and `PARENT_OF`; it never touches `LINKS_TO`. When the
answer lives in a linked PDF whose own text isn't close to the query embedding ("see the Q&A on
nitrosamines"; the limit is in the linked PDF), the gold doc is unreachable by dense search alone — the
T3 multi-hop failure mode the benchmark measures. Two gaps: **(1) dead config** — `GraphRetrievalConfig
(max_hops, edge_types)` is parsed, threaded, asserted in tests, and read by nothing; **(2) no edge
hygiene** — 94.6 % of edges are nav boilerplate (§0.4), so naive expansion drowns. Non-goal: single-shot
expansion, *not* agentic/iterative retrieval.

### Approach

A new strategy `hierarchical_links` registered alongside `hierarchical`. It reuses the baseline
seed-and-merge verbatim, then adds **one** bounded `LINKS_TO` expansion round-trip:

1. **Seed** (identical to baseline): `db.index.vector.queryNodes('ema_chunk_embedding', $k, $q)` →
   `HAS_CHUNK`/`PARENT_OF` small-to-big merge → seed nodes, `hop=0`, `retrieval_origin="seed"`/`"parent"`.
2. **Collect** the distinct seed `:Document` ids.
3. **Expand** `-[r:LINKS_TO*1..max_hops]->` from the seed docs over the **P1-cleaned, typed** edge set,
   with the property guard `ALL(e IN relationships(p) WHERE e.link_context IN $contexts)` (+ optional
   `e.document_type IN $doctypes`); the demoted `NOT linked.is_nav_hub` is an optional residual safety-net.
4. **Evidence per linked doc**: its top-`evidence_per_doc` leaves by query similarity (client-side
   cosine), stamped `{…, hop≥1, via_edge:"links_to", seed_doc_id}`, `retrieval_origin="links_to"`.
5. **Dedup + cap**: merge seed (`k`) and expansion (`expand_k`); on collision keep the higher score.
6. **Score** expanded nodes by re-scoring against the query (so a strong linked PDF can outrank a weak
   seed); `decay` is the fallback only when no embedding is available.

**`edge_types`** generalizes (per P1, §0.8) from a relationship-label whitelist to a **`link_context`
whitelist** filtered on the edge's `r.link_context` property (default `[file_component, card_or_listing,
inline]`); an optional `graph.document_types` predicate restricts to specific EMA card types
(`guideline`, `assessment-report`, …). An unknown context value raises `NotImplementedError` listing the
implemented set — the field stays real without speculative traversals.

**Edge hygiene is now P1's job, structurally (§0.8).** Track B's retriever **assumes the cleaned, typed
edge set**: main-content scoping has already removed the 74 chrome targets (94.4 % of the old edges) at
extraction time, so the expansion query filters on **edge properties** — prefer `r.link_context =
'file_component'` (the HTML→PDF cards) and/or `r.document_type IN $doctypes`, far more precise than the
old URL-shape `source_type` guard. The first draft's build-time **`is_nav_hub` degree-cap is demoted to a
secondary safety-net** (`ensure_nav_hub_flags`, idempotent property write, no rebuild) — kept only to
catch any residual high-in-degree target that survives P1, not as the primary filter. If P1 has not yet
landed when Track B is implemented, `is_nav_hub` + the `source_type` guard is the interim fallback.

> **⚠ Review-driven corrections.**
> - **Re-score must be calibrated cosine.** Comparability of seed score (`db.index.vector.queryNodes`
>   cosine) and the client re-score holds **only** if the client computes normalized cosine
>   (`dot/(‖q‖·‖v‖)`). Stored BGE vectors are L2-normalized (§0.3), so this is fine — but the spec must
>   *state* it and add a live-smoke assertion that a seed chunk re-scored client-side reproduces its index
>   score within tolerance. Do not claim comparability without it.
> - **`_FakeEmbed` lacks `get_query_embedding`.** The retriever path calls
>   `self._embed.get_query_embedding(...)` (`property_graph.py:460`), but the existing `_FakeEmbed` double
>   only exposes `get_text_embedding_batch` (it's used by build tests, never a retriever). Add a test-plan
>   prerequisite: extend `_FakeEmbed` (or add `_FakeQueryEmbed`) with a deterministic
>   `get_query_embedding(text)->list[float]` that yields the intended cosine ordering for the re-score
>   tests.
> - **`recall@k` "bounded below by baseline" only if no displacement.** If re-scored expansion nodes can
>   push a seed node out of the top-k, T1/T2 recall@k can regress. Return **`k` seed ∪ up-to-`expand_k`
>   expansion as a union** (total `k+expand_k`, no displacement) and say so — or drop the guarantee.
> - **`decay` had two contradictory definitions.** Pin it to one trigger: `decay` is the seed-score
>   multiplier used **only** when a linked doc's evidence is a root chunk with no embedding to re-score.
>   The global "re-score off" path is a separate, explicit switch.
> - **`is_nav_hub` goes stale** after any future `links_only` re-pass. Either recompute it inside the
>   links pass, or document that `ensure_nav_hub_flags` must be re-run after one.

### New + touched files

All inside `harness/indexing/property_graph.py` (where `HierarchicalPGRetriever` lives) + a YAML + a
dataclass extension — **no new module**, and `__init__.py` is unchanged (the module is already imported,
so the new decorator fires for free):

| Path | Change |
|------|--------|
| `harness/indexing/property_graph.py` | **Add** `LinkExpandingPGRetriever(BaseRetriever)` (sibling of `HierarchicalPGRetriever`, reuses its seed `_QUERY` via a shared constant), the `_LINKS_QUERY` constant, a client-side re-score helper, `ensure_nav_hub_flags(...)`, and `@register_retriever("hierarchical_links") build_link_expanding_retriever`. **`HierarchicalPGRetriever` / `build_hierarchical_retriever` untouched.** |
| `harness/indexing/profiles.py` | **Extend** `GraphRetrievalConfig` (5 fields, below). No new dataclass. |
| `harness/configs/index/neo4j_hier_links.yaml` | **New** — `index:` block identical to `neo4j_hier`, `retrieval.strategy: hierarchical_links`, populated `retrieval.graph`. Same live graph, no rebuild. |
| `tests/test_indexing_{profiles,property_graph}.py` | **Add** Track-B tests (below). |
| `docs/RETRIEVAL.md` | document `hierarchical_links` + `is_nav_hub` + that `graph.*` is now consumed. |

### Profile-schema changes

```python
@dataclass
class GraphRetrievalConfig:
    max_hops: int = 1
    edge_types: list[str] = field(default_factory=lambda: ["links_to"])
    # ── Track B ──────────────────────────────────────────────────────────────
    expand_k: int = 5                 # max linked docs contributed (UNION with seed, no displacement)
    evidence_per_doc: int = 1         # leaf chunks per linked doc
    decay: float = 0.5               # seed-score multiplier ONLY for root-chunk evidence (no embedding)
    include_incoming: bool = False    # also walk <-[:LINKS_TO]- (authority); off by default
    allowed_target_types: list[str] = field(default_factory=lambda: ["pdf", "html"])
    max_target_indegree: int = 100    # nav-hub cap (deliberately loose; see Approach)
```

`from_dict` validates (`expand_k>=0`, `evidence_per_doc>=1`); `RetrievalConfig.from_dict` already
delegates to `GraphRetrievalConfig.from_dict`, so the keys parse with no `RetrievalConfig` change. All
defaulted → existing `neo4j_hier.yaml` and every `test_indexing_profiles.py` assertion keep passing.

### Decision points

| # | Decision | **Recommended** (one-line why) |
|---|----------|--------------------------------|
| 1 | Edge filter | **P1's typed edges + query-time `link_context`/`document_type` predicate** (primary) — chrome removed structurally at extraction; prefer `file_component` cards. **`is_nav_hub` degree-cap demoted to a residual safety-net** (interim fallback if P1 hasn't landed). |
| 2 | Evidence selection | **top-`evidence_per_doc` leaves by query similarity (client-side cosine; no GDS on Community)** — returns the part that answers the query, matches how recall is scored. |
| 3 | Direction | **outgoing-only default; `include_incoming` behind a flag** — the card→PDF signal is directional; incoming authority is an ablation *after* `is_nav_hub` tempers the hubs. |
| 4 | Scoring | **re-score (calibrated cosine); `decay` only as the no-embedding fallback** — keeps seed + expansion on one comparable scale. Cross-encoder rerank is out of scope. |
| 5 | Budget location | **extend `GraphRetrievalConfig`** — the one switching mechanism; finally makes `graph.*` load-bearing. |

### Test plan (existing `_FakeStore`/`_FakeEmbed` doubles + a `_FakeLinkStore`; no live Neo4j)

Profiles: `test_graph_config_new_fields_default`, `…_parses_overrides`, `…_rejects_bad_expand_k`,
`…_rejects_bad_evidence_per_doc`, `test_links_profile_parses`, `test_hierarchical_still_registered`.
Retriever (with the **extended `_FakeEmbed`** per the correction): `test_link_retriever_seed_only_when_no_links`,
`…_expands_to_linked_doc` (asserts `hop==1`, `via_edge`, `seed_doc_id`, `retrieval_origin="links_to"`),
`…_respects_max_hops` (Cypher `*1..2` vs `*1..1` string assertion), `…_filters_nav_hub`,
`…_caps_expansion` (≤`expand_k` docs, ≤`evidence_per_doc` leaves), `…_union_no_seed_displacement`
(new — seed nodes survive even when expansion outranks them), `…_dedup_keeps_higher_score`,
`…_rescore_can_outrank_seed` (+ `decay` fallback path), `…_unknown_edge_type_raises`,
`test_ensure_nav_hub_flags_query_shape`, `test_link_builder_threads_graph_config`. One gated live smoke:
a known gold seed→PDF pair from `benchmark.jsonl` is reached.

### Acceptance

`EMA_INDEX_PROFILE=neo4j_hier_links` → `build_retriever` returns `LinkExpandingPGRetriever`;
`get_workflow(...)` unchanged; baseline `_QUERY` byte-for-byte unchanged. Changing `max_hops`/`edge_types`
in YAML demonstrably changes behavior (gap closed). `ensure_nav_hub_flags` flags the 10 nav hubs
(in-degree 21,956 → `is_nav_hub`); expansion excludes them. On the 45-item benchmark, **linked-doc
recall** (§4) for T3/T4 is strictly higher than `hierarchical`, and `recall@k` does not regress on T1/T2
(union, no displacement). Re-score reproduces seed index scores within tolerance (calibration smoke).
`pytest`/`ruff`/`mypy` green, no live Neo4j in CI.

### Estimated effort

**3–4 evenings.** E1: schema + YAML + offline tests. E2: retriever + 2 Cypher constants + calibrated
re-score + `_FakeLinkStore` tests. E3: `ensure_nav_hub_flags` + live smoke + benchmark linked-doc-recall
vs baseline. E4 (buffer): tune cap/`allowed_target_types`, docs, ruff/mypy.

---

## 3. Track C — `property_graph_native`: the idiomatic-LlamaIndex learning track

> **Verdict: flawed → substantially reframed.** Track C is a *learning vehicle*, deliberately separate
> from the production `property_graph`/`hierarchical` stack: optimize for idiomatic LlamaIndex usage,
> fast experiment turnaround on coherent subgraphs, and store swappability — **not** throughput. The
> adversarial review **refuted the first draft's "100 % native, zero custom Cypher" headline** against
> the installed source. The honest finding — *where the native sub-retrievers genuinely work vs. where a
> small, explicitly-justified custom layer is unavoidable* — **is the deliverable of this track.**

### Problem

Every retrieval path on this branch is hand-rolled Cypher. We have no in-repo example of the **native**
`PropertyGraphIndex` retrieval surface (`VectorContextRetriever`, `CypherTemplateRetriever`,
`get_rel_map`), nor a documented account of *why* custom Cypher is needed. Three gaps: no idiomatic
reference, no fast experiment loop (the live graph is the full build on one `neo4j:5.26` Community server
= **exactly one user DB**), and no swappable store (`neo4j_store_from_env()` is hard-wired). Track C is
also the seam where custom node/edge schema constraints and IDMP ontology mapping plug in **without
reshaping the pipeline**.

### What the native path actually does and doesn't do (the refuted claims)

The review read `faiss/base.py`, the PG `sub_retrievers/`, and `graph_stores/` and established:

1. **`VectorContextRetriever` seeds on `__Entity__` embeddings** — which on this host are **unembedded**
   (§0.3). A naive native retriever against the live store returns **nothing**. *(This part the first
   draft got right and foregrounded — it's the single most important trap.)*
2. **A bare `FaissVectorStore` cannot back the native seed.** Its `query()` returns **positional integer
   ids** (`"0","1","2"`, `faiss/base.py:220`), not `ChunkNode` ids; `VectorContextRetriever` then calls
   `graph_store.get(ids=…)` with those ints and finds nothing. And `from_existing(nodes=[],
   embed_kg_nodes=False, vector_store=faiss)` **never populates FAISS** in the first place. So the "Simple
   store + external FAISS + native VectorContextRetriever, zero custom Cypher, runs in CI" recommendation
   is **unbuildable as written**.
3. **Native sub-retrievers return *triplet* TextNodes** (`text="subj → rel → obj"`), **not** the
   `{source_url, doc_id, matched_chunk}` shape the benchmark reads. Source-text/provenance recovery needs
   nodes inserted via `upsert_llama_nodes` (with `VECTOR_SOURCE_KEY`/`TRIPLET_SOURCE_KEY` plumbing), not a
   raw `upsert_nodes(ChunkNode)`.
4. **`LINKS_TO` is `Document→Document`, not incident to a chunk seed.** From a chunk seed, the topology is
   `chunk → (HAS_CHUNK⁻¹) Document → (LINKS_TO) Document → (HAS_CHUNK) chunk` — reaching a linked doc's
   chunk natively needs **`path_depth ≥ 3`**, not `1`. And `get_rel_map` has **no `edge_types` filter**
   (only `depth`/`limit`/`ignore_rels`), so "honors `graph.edge_types` natively" is false — restricting to
   `links_to` requires a `CustomPGRetriever` post-filter or Cypher.
5. **Community = one DB.** Writing Track C's own `:Document`/`:Chunk` nodes (same labels, deterministic
   ids) into the *shared* live DB collides with the production graph. Track C must either be **read-only**
   against the existing graph or run in its **own container/DB**.

### Approach (corrected)

A new index kind `property_graph_native` + strategy `pg_native` in a new module
`harness/indexing/property_graph_native.py`, built from the **same `IngestedDoc` IR**, with **no LLM
extraction**. Because it consumes the IR, Track C **inherits P1's cleaned, typed links for free**
(`IngestedDoc.links` already carry `link_context`/`document_type`; `to_native_graph` stamps them on its
`LINKS_TO` relations) — no edge-hygiene work of its own. Two honestly-scoped profiles:

- **`pg_native_subgraph` (recommended default — the learning sandbox).** Build a *real*
  `PropertyGraphIndex` over a **`SimplePropertyGraphStore`** (in-memory/JSON; `supports_vector_queries=
  False`, confirmed) on a small `link_closure` subgraph, **inserting through the index's own
  `upsert_llama_nodes` path so node-id↔embedding↔source-text mapping is maintained** (this is what fixes
  refuted-claim #2/#3 — the embeddings live in the index with correct ids, and source text is
  recoverable). Retrieve with a native `VectorContextRetriever` for the **chunk vector seed**, then —
  because of refuted-claim #4 — reach `LINKS_TO` neighbors with a **`CustomPGRetriever`** whose
  `get_rel_map`/store traversal is post-filtered to `links_to` + `source_type`. Output is mapped to the
  shared `{source_url, doc_id, matched_chunk, retrieval_origin}` contract (§0.6) by a small adapter.
- **`pg_native_neo4j` (opt-in, scale).** **Read-only** against Track A's existing graph + `ema_chunk_
  embedding` index (no `to_native_graph` upsert into the shared DB → no collision, no re-embed). The seed
  is a native `CypherTemplateRetriever` over `ema_chunk_embedding`; `LINKS_TO` expansion is the same
  post-filtered traversal. For full isolation (a *different* graph), spin a throwaway container on alt
  ports (compose already parameterizes `NEO4J_*_PORT`/`NEO4J_URI`) and run the `subgraph` build into it.

**The native-vs-custom ledger (the track's whole point).** Every non-native line is justified against the
native alternative it replaces:

| Need | Native option | Verdict | Track C uses |
|------|---------------|---------|--------------|
| Chunk vector seed (Simple store) | `VectorContextRetriever` + vector store **wired through the index** | ✅ works once nodes go in via `upsert_llama_nodes` | **native `VectorContextRetriever`** |
| Chunk vector seed (Neo4j, leaf index) | native `vector_query` targets `__Entity__` (unembedded) | ❌ can't target `:Chunk` natively | **`CypherTemplateRetriever`** (native class, one parameterized vector query) |
| `LINKS_TO`-only expansion | `get_rel_map` has no edge-type filter; doc-doc edge needs depth≥3 | ❌ | **`CustomPGRetriever`** post-filtered to `links_to` + `source_type` (justified) |
| Output `{source_url,doc_id}` | native returns triplet TextNodes | ❌ | **small adapter** resolving ref-doc → Document, stamping metadata |

> **⚠ Review-driven corrections folded in.**
> - **`link_closure` must read `parsed_documents`, not raw collections.** The first draft reused
>   `select_subset` from `scripts/backfill_parsed_documents_subset.py`, which reads **`web_items` +
>   `parsed_pdfs`** (the *write-side* backfill) — a second Mongo reader over non-`parsed_documents`
>   collections, violating Ground Rule 1. **Fix:** implement `link_closure` as a **post-`ingest` filter
>   over `ingest(profile)→IngestedDoc`** using the already-extracted `IngestedDoc.links` (select N HTML
>   seed docs whose links resolve in-corpus + pull their linked docs). No new reader.
> - **`path_depth ≥ 3` + edge-type post-filter**, not `max_hops=1` (refuted-claim #4). State the topology
>   explicitly; set the profile accordingly; acknowledge the post-filter is the justified custom bit.
> - **Nav in-degree filter is inert on small subgraphs** — boilerplate hubs have *subgraph-local*
>   in-degree ≈ number of seed pages (~10), never near a cap of 1000. **Fix:** for Track C, key edge
>   hygiene on **target `source_type` (prefer PDF cards)** as the primary signal and **drop the in-degree
>   cap**, documenting that global-degree edge classification is **Track B's job** (Track C explicitly
>   does not re-solve it). Make `test_nav_filter` reflect realistic subgraph-local degrees.
> - **Output-shape adapter is mandatory** (refuted-claim #3): add a test asserting returned nodes carry
>   `source_url`/`doc_id`; do not claim "the benchmark metric works identically" without it.

### New + touched files

**New:** `harness/indexing/property_graph_native.py` — `to_native_graph(docs)` (pure IR→`:Document`
entities + leaf `ChunkNode`s + `HAS_CHUNK` + `LINKS_TO`; **no `PARENT_OF`** — small-to-big stays Track
A's job), `store_from_profile(profile)` (dispatch `store.kind`: `simple` → `SimplePropertyGraphStore`,
`neo4j` → `neo4j_store_from_env()`), `link_closure_filter(docs, scope)` (post-`ingest` selection),
`@register_index("property_graph_native") build_property_graph_native_index(...)` (insert via
`upsert_llama_nodes`; persist for `simple`; **read-only open for `neo4j`**),
`@register_open("property_graph_native") open_*` (P0), `NativeLinkRetriever(CustomPGRetriever)` (the
justified `links_to` post-filter + output adapter), `@register_retriever("pg_native")
build_pg_native_retriever(...)`. · `harness/configs/index/pg_native_subgraph.yaml` (default: `store.kind:
simple`, `scope.mode: link_closure`, `scope.seeds: 10`, `graph.max_hops: 3`). ·
`harness/configs/index/pg_native_neo4j.yaml` (opt-in, read-only). ·
`tests/test_indexing_property_graph_native.py`.

**Touched:** `harness/indexing/__init__.py` (import the module); `harness/indexing/profiles.py` (additive
fields below); `docs/RETRIEVAL.md` (the native-vs-custom ledger + the `__Entity__` pitfall).

### Profile-schema changes (all additive/defaulted; `neo4j_hier.yaml` untouched)

```python
@dataclass
class StoreConfig:
    graph: str = "neo4j"
    kind: str = "neo4j"                 # NEW (shared with Track A): "neo4j" | "simple"
    persist_path: str | None = None     # NEW: JSON dir for kind="simple" (graph + FAISS co-persist)

@dataclass
class ScopeConfig:
    # …existing committee/topic_prefix/limit…
    mode: str = "scope"                 # NEW: "scope" | "link_closure"
    seeds: int = 10                     # NEW: N seed HTML pages for link_closure
    seed_urls: list[str] = field(default_factory=list)  # NEW: explicit seeds (reproducible; overrides seeds)

@dataclass
class IndexConfig:
    # …existing…
    schema_constraints: str | None = None  # NEW seam: path to allowed labels/relations YAML (validator-only)
    ontology: str | None = None            # NEW seam: "concepts" -> harness.ontology.load_concepts (tagger stub)
```

`pg_native` reads the **already-present** `retrieval.k` / `graph.max_hops` / `graph.edge_types` and
genuinely honors them (unlike `hierarchical`). **Pin `seed_urls`** in `pg_native_subgraph.yaml` so
subgraphs are reproducible host-to-host (Mongo scan order is non-deterministic).

**Seams (interfaces only, no implementation, honoring the no-LLM-extraction non-goal):**
`index.schema_constraints` → a **validator pass** over IR-derived nodes/edges before upsert (reuse the
`SchemaLLMPathExtractor` triple-schema shape for forward-compat, but **run no extractor**).
`index.ontology: concepts` → `harness.ontology.load_concepts()` (~100 IDMP labels, verified to exist) →
a `:Document.idmp_concepts: list[str]` property by lightweight string match (a documented **stub**;
IDMP RDF under `~/Nextcloud/Datasets/` is the future richer source). Both run on the **IR (pre-upsert)**
so they're store-agnostic.

### Decision points

| # | Decision | **Recommended** |
|---|----------|-----------------|
| A | Retrievable text location | **`ChunkNode` + `HAS_CHUNK`** (matches the benchmark "owning doc" recall; uniform provenance) over doc-properties (breaks chunk seeding) |
| B | How the native seed lands on chunks | **`pg_native_subgraph`: `SimplePropertyGraphStore` + index-managed vector store via `upsert_llama_nodes`** (native `VectorContextRetriever`, CI-friendly); **`pg_native_neo4j`: `CypherTemplateRetriever` over `ema_chunk_embedding`** (scale, read-only). **Reject** embedding `__Entity__` (re-embeds corpus, wrong granularity) and **reject** bare `FaissVectorStore` (positional-id mismatch). |
| C | `PARENT_OF` / small-to-big | **omit** (keep Track C minimal/link-focused; small-to-big is Track A's) |
| D | Rollback (Community 1-DB) | **deterministic rebuild-from-IR on the scoped subset** (ids already deterministic; `--reset` clean on a *small* graph) + JSON snapshot for `simple`; throwaway container (D2) only when an experiment needs a second live graph |
| E | `link_closure` source | **post-`ingest` filter over `IngestedDoc.links`** (no new Mongo reader — supersedes the first draft's raw-collection `select_subset` reuse) |
| F | Edge hygiene at this scale | **target `source_type` (prefer PDF) only; no in-degree cap** (the global-degree filter is Track B's; the cap is inert on ~10-page subgraphs) |

### Test plan (`tests/test_indexing_property_graph_native.py`; pure-IR + mongomock + `_FakeStore`/`_FakeEmbed`)

`test_to_native_graph_structure` (`:Document` per doc, `HAS_CHUNK` per chunk, **no `PARENT_OF`**, only
in-corpus `LINKS_TO`) · `test_native_links_to_dropped_when_target_absent` ·
`test_native_build_embeds_leaves_only` · `test_store_from_profile_dispatch` (`simple`→Simple,
`neo4j`→monkeypatched, unknown→`ValueError`) · `test_simple_store_roundtrip` (build → persist →
`from_persist_path` → counts survive) · `test_link_closure_filter` (over `ingest()` output, **not** raw
collections — returns seed HTML + linked docs, connected) · `test_pg_native_registered` (+P0 open) ·
`test_pg_native_retriever_honors_graph_config` (`path_depth`/`similarity_top_k` reflect
`max_hops`/`k`) · `test_output_adapter_stamps_source_url_doc_id` (**the contract test** — native triplet
output is mapped to `{source_url,doc_id}`) · `test_source_type_edge_filter` (PDF card kept, with
realistic subgraph-local degrees) · `test_profile_parses_new_fields` · `test_ontology_seam_stub` (runs on
the IR, store-agnostic).

### Acceptance

`import harness.indexing` registers `property_graph_native` + `pg_native` (P0 open too); `neo4j_hier`
unchanged. `EMA_INDEX_PROFILE=pg_native_subgraph` builds a `link_closure` subgraph into a
`SimplePropertyGraphStore` and answers a query end-to-end via a **native `VectorContextRetriever`**
(chunk seed through the index-managed vector store) **plus** the justified `CustomPGRetriever` `links_to`
expansion, on **CPU in CI, no live Neo4j** — and **returned nodes carry `source_url`/`doc_id`** (adapter
test). `pg_native_neo4j` is **read-only** against the live graph (no upsert collision, no re-embed).
The native-vs-custom ledger is reproduced in `docs/RETRIEVAL.md` with each custom line justified.
`link_closure` reads only `parsed_documents` (via `ingest`); seams parse + thread with **no LLM
extraction**. `corpus.jsonl` never read. `pytest`/`ruff`/`mypy` green.

### Estimated effort

**4–5 evenings** (up from the first draft's 3–4 — the native seed must be wired through the index, not a
bare FAISS store, and the `links_to` `CustomPGRetriever` + output adapter are real work). E1: schema +
YAMLs + `to_native_graph` + registry/P0 + pure-IR tests. E2: `SimplePropertyGraphStore` build via
`upsert_llama_nodes` + native `VectorContextRetriever` + roundtrip/adapter tests. E3: `link_closure`
post-`ingest` filter + `NativeLinkRetriever` (`links_to` post-filter) + Neo4j read-only path. E4: seams
(`schema_constraints`/`ontology` stubs) + docs ledger. E5 (buffer): live smoke + ruff/mypy.

---

## 4. Comparison harness — `harness/retrieval_eval.py` (retrieval-level, Phoenix-traced)

> **Verdict: solid → corrections folded in.** Grades Track A vs `hierarchical` vs Track B vs Track C with
> **retrieval-level** metrics against `benchmark/benchmark.jsonl`, per T1–T4, **without** the archived
> LLM-judge loop, traced in Phoenix. Ships **in lockstep with Track B** so "does expansion help?" has a
> number. Consumes the registry; it is **not** a builder and registers nothing.

### Problem

The eval + judge suite is archived; there is no way to score a retriever on this branch short of
eyeballing Chainlit. We need an **answer-free, track-agnostic, link-fair, traced, CI-testable** judge.

### Approach

One module + a thin CLI. Flow: load benchmark → per profile, `load_index_profile(name)` →
`open_index(profile)` (P0 dispatch; **never rebuild** during eval) → `build_retriever` → per item,
retrieve → score vs gold → aggregate per type → write artifact.

**Gold matching** (the load-bearing surface): a query *hits at k* if any top-k node's owning doc
`source_url` matches any `gold_sources[].url`, after URL normalization (lowercase host, strip `www.`,
strip trailing `/`, drop query+fragment).

> **⚠ Review-driven correction — `doc_id` dual-key is near-inert.** `doc_id = sha256(source_url)` is
> computed from the **raw** URL at ingest, so `sha256(normalize_url(u))` almost never equals a stored
> `doc_id`. The **`source_url`-normalized branch is the real matcher**; the `doc_id` branch only helps
> the narrow case where a retriever omits `source_url` but keeps the pipeline `doc_id`. Keep it as a
> fallback, but **document it as such** — don't present it as load-bearing robustness.

**Metrics:** `recall@k` (k ∈ {5,10,20}) + `MRR` + **`linked_doc_recall`** (gold reached **only** via a
`retrieval_origin="links_to"` node — the entire thesis of Track B; `None`/n-a for flat tracks, so the
harness runs against the baseline **today**, before Track B exists). Drop precision/nDCG (≈1 gold
url/item → noise).

> **⚠ Review-driven correction — multi-gold is material.** 6 items have >1 `gold_source`
> (**all five T4** + T2-010). For T4 synthesis, "reached **every** gold source" is the point. **Commit
> in-spec:** report **both `recall_any@k` and `recall_all@k`; lead with `recall_all` for T3/T4,
> `recall_any` for T1/T2.** Add a 3-gold (T4-003-shaped) fixture test.

**Link-fair budget (D3):** retrieve once at `k=max(k_values)`, **truncate the scored list to top-k by
score** for the headline `recall@k` (apples-to-apples vs the flat baseline), and report
`linked_doc_recall` **uncapped** separately (where expansion is allowed to shine).

**Phoenix:** reuse the existing wiring (`phoenix.otel.register(project_name=…, auto_instrument=True)`,
`app.py:142–147`; `PHOENIX_DISABLED` guard, `app.py:35`; span pattern `utils.py:189–194`). One span per
query under a dedicated `ema-nlp-retrieval-eval` project, stamping `ema.eval.{track,profile,bench_id,type,
k,hit_at_k,rank,linked_doc_hit}` derived from `node.metadata["source_url"]/["doc_id"]` (the grading
result; the auto-instrumented `BaseRetriever.retrieve` already emits the per-document retrieval span).

**Output** (not `results/` — a Nextcloud symlink): a configurable `EMA_EVAL_OUT_DIR` default to a
git-ignored repo-local `retrieval_eval_runs/<run_id>/` with `per_query.jsonl`, `summary.json`,
`summary.md` (track rows × T1–T4 columns). **Plus a per-run diagnostic** counting returned nodes with
both `source_url` and `doc_id` null (a retriever violating §0.6 surfaces loudly, not as quietly-zero
recall).

> **⚠ Other corrections.** (i) `gold_sources[].page` is **always null** across all 52 entries → page
> granularity is **moot for v1** (a one-line note, not an open question). (ii) **Drop `eval_k`** from the
> profile schema — it's scope creep; the CLI already takes `--k` and retrieves once at `max(k)`. Leaving
> it out keeps `profiles.py` and `test_indexing_profiles.py` **untouched**. (iii) State that `"parent"`
> origin folds into the seed bucket (don't misclassify baseline merges as expansion). (iv) Mechanize
> "`corpus.jsonl` never read" as a **unit test** (assert the string is absent from the module and
> `BENCH_PATH` resolves under `benchmark/`), not reviewer diligence.

### New + touched files

`harness/retrieval_eval.py` (**new**, ~250 lines: `load_benchmark`, `normalize_url`, `gold_match`,
`BenchmarkItem`, `RetrievalMetrics`, `ProfileResult`, `_eval_one_profile`, `evaluate_profiles`,
`write_artifacts`, `default_out_dir`, `_make_eval_span`, CLI) · `tests/test_retrieval_eval.py` (**new**,
`_FakeRetriever` + 4-item hand-built fixture) · `harness/indexing/property_graph.py` (**1-line**: stamp
`retrieval_origin="seed"`/`"parent"` on baseline nodes) · `docs/RETRIEVAL.md` (metric defs + the §0.6
retriever contract). **No profile-schema change** (after dropping `eval_k`). Each track contributes its
own YAML to the default `sorted(glob)` sweep — this spec adds none.

### Decision points

| # | Decision | **Recommended** |
|---|----------|-----------------|
| D1 | Metric set | `recall@{5,10,20}` + `MRR` + `linked_doc_recall` (+ `recall_all` for T3/T4); drop precision/nDCG |
| D2 | Queries vs paraphrases | **`question` only** for the leaderboard; `--paraphrases` as a separate robustness side-report |
| D3 | Link fairness | **budget-fair top-k-by-score headline + uncapped `linked_doc_recall`** |
| D4 | Where eval runs | **one process, `--open-only` ON**, single live graph; distinct-store tracks (A FAISS, C subgraph) run as separate invocations (Community 1-DB) |
| D5 | Phoenix | dedicated `ema-nlp-retrieval-eval` project, `PHOENIX_DISABLED`-aware |

### Test plan (`_FakeRetriever` + tiny fixture; no live Neo4j/Phoenix/GPU)

`test_normalize_url_*` · `test_gold_match_by_source_url` · `test_gold_match_by_doc_id_when_url_differs`
(+ the documented caveat) · `test_gold_match_miss_returns_none` · `test_recall_and_mrr_math` (hand-computed)
· `test_recall_at_k_truncation` · `test_recall_all_vs_any_multigold` (**new**, 3-gold T4 item) ·
`test_linked_doc_recall_credits_expansion_only` · `…_not_double_counted` · `…_na_without_origin_metadata`
· `test_parent_origin_folds_into_seed` (**new**) · `test_evaluate_profiles_sweeps_two_fakes`
(monkeypatch `load_index_profile`/`open_index`/`build_retriever`) · `test_breakdown_by_type_keys` (per-type
`n` sums to 45) · `test_null_provenance_diagnostic` (**new**) · `test_out_dir_env_override` (never resolves
to `results/`) · `test_phoenix_disabled_no_raise` · `test_corpus_jsonl_never_read` (**mechanized leakage
guard**).

### Acceptance

`python -m harness.retrieval_eval --profiles neo4j_hier` scores all 45 items and writes a T1–T4
`recall@k`/`MRR` `summary.md` — **no LLM, no judge, no archived code imported**. Adding a Track-B profile
yields a side-by-side table with a nonzero `linked_doc_recall` for B and n-a for baseline.
`recall_all`/`recall_any` both reported (lead `recall_all` for T3/T4). Phoenix project shows one span/query;
`PHOENIX_DISABLED=1` → span-free + still succeeds. Output never lands in `results/` unless `EMA_EVAL_OUT_DIR`
says so. `corpus.jsonl` never read (CI-enforced). `pytest`/`ruff`/`mypy` green, no live infra.

### Estimated effort

**~3 evenings.** E1: matcher + metric math (incl. `recall_all`) + artifact writers. E2: sweep +
`open_index` (P0) + Phoenix span + CLI + baseline `retrieval_origin` stamp + live smoke. E3: tests +
`_FakeRetriever` + docs.

---

## 5. Sequencing

```
P0  registry-level open dispatch + §0.6 retriever contract     (~0.5 evening; unblocks A & C)
└─▶ A   vector_flat (control arm)                               (~2 evenings)  ── ships first
    └─▶ HARNESS  retrieval_eval (scoreboard)                    (~3 evenings)  ── lands with/just before B
        └─▶ P1  link-extraction upgrade (clean, typed edges)    (~2–3 evenings; gates B, feeds C via IR)
            └─▶ B   hierarchical_links (the cornerstone)        (~3–4 evenings) ── on the P1-cleaned edge set
                └─▶ C   property_graph_native (learning track)  (~4–5 evenings) ── inherits P1 edges via IR
```

Rationale: **P0 first** (Track A's "needs-revision" traced to the hardcoded `open_index`; doing it once
unblocks every non-Neo4j track). **A is the smallest and the control** every later number is read against.
The **harness lands with or just before B** so Track B's lift is a measured `linked_doc_recall` delta, not
a vibe (the harness runs against the baseline before B exists, so it can ship early). **P1 immediately
before B**: Track B's retriever design *assumes* the cleaned, typed edge set — building B on the raw
94.4 %-chrome graph would force the degree-cap workaround and measure link-recall against polluted edges.
P1 is edge-only (no chunk/vector rebuild, ~minutes of Neo4j work) and **Track C inherits the same cleaned
links through the shared `IngestedDoc` IR** at no extra cost. **B before C**: B is the declared cornerstone
and reuses the live graph (cheap), while C is a separate-store learning vehicle whose value is partly the
native-vs-custom *documentation* it produces. Each lands as its own `.claude/work/` unit with a
`DECISIONS.md` entry and a `.claude/HISTORY.md` row.

---

## 6. Consolidated open questions

1. **(A) Stale-index policy.** `vector_flat`'s persisted FAISS silently goes stale when the Neo4j build
   changes. Stamp a build manifest (doc count, profile hash) in `persist_dir` and warn on drift, or treat
   rebuild as manual? *(Lean: manifest + warn, follow-up.)*
2. **(A) FAISS index type at 5.82 M.** `IndexFlatIP` (exact, ~22 GB, ~10–50 ms) is the honest control —
   keep flat (a control arm must not add ANN recall loss), or ever allow IVF/HNSW for latency? *(Lean:
   stay flat.)*
3. **(B) Lazy vs explicit nav-hub flagging.** `ensure_nav_hub_flags` auto-run on first retrieve (friction-
   free, writes from a query path) vs explicit `--flag-nav-hubs` ops step (cleaner, forgettable)? *(Lean:
   explicit; recompute inside any future `links_only` pass to avoid staleness.)*
4. **(B) `expand_k` global vs per-seed-doc; hop-2.** A high-fan-out seed can monopolize a global
   `expand_k`; and is any T3 case 2 hops (page → index page → PDF)? Measure linked-doc recall at
   `max_hops=2` on T3 before raising the default from 1.
5. **(B→later) Re-add `ExtractedLink.kind` to `LINKS_TO`?** Only if `source_type`-level filtering proves
   too coarse for a specific benchmark failure (per the "justify complexity by a benchmark failure" lock)
   — it costs a full `links_only` re-pass.
6. **(C) `pg_native_neo4j` isolation.** Read-only against the live graph (convenient, couples tracks) vs a
   throwaway container (clean A/B). *(Lean: read-only default; container when an experiment needs a
   distinct graph.)*
7. **(C) Schema-constraints format.** Reuse the `SchemaLLMPathExtractor` triple-schema shape (forward-
   compat, validator-only for now) vs a bespoke allow-list. *(Lean: reuse the LlamaIndex shape.)*
8. **(Harness) Score comparability across stores.** Cosine from the Neo4j chunk index vs FAISS (Track A)
   aren't on one raw scale; budget-fair top-k truncation is per-retriever by its own score, so `recall@k`
   is comparable but **raw `per_query.jsonl` scores are not** — flag in the artifact header.

---

## Appendix — load-bearing evidence (so a reviewer needn't re-derive)

**Verified API facts (read from the installed `.venv` source, llama-index-core 0.14.22 / faiss-cpu 1.14.2
/ graph-stores-neo4j 0.7.0):**

- `embed_nodes()` skips the embed model for any node with `.embedding is not None`
  (`llama_index/core/indices/utils.py`) → Track A's `MockEmbedding` zero-re-embed path is real.
- `Neo4jPropertyGraphStore.structured_query` runs `value_sanitize()` (`sanitize_query_output=True`),
  which **drops list properties ≥128 elements** (`graph_stores/utils.py`, `LIST_LIMIT=128`) → strips
  1024-d embeddings; a **raw driver** or `sanitize_query_output=False` returns them intact.
- `FaissVectorStore`: `stores_text=False`; `query()` returns **positional integer ids**
  (`faiss/base.py:220`); `from_persist_dir(persist_dir)` reload path confirmed.
- `VectorContextRetriever` vector-searches `__Entity__` embeddings via the store's `vector_query`; with a
  Simple store it routes through `vector_store.query()` **only if nodes were inserted through the index**
  (so ids align). `get_rel_map` has **no `edge_types` filter** (only `depth`/`limit`/`ignore_rels`).
  Native sub-retrievers emit triplet `TextNode`s.
- `SimplePropertyGraphStore`: `supports_vector_queries=False`, `supports_structured_queries=False`;
  `persist`/`from_persist_path` JSON confirmed.
- Phoenix: `phoenix.otel.register(project_name, auto_instrument=True, endpoint=…)` (`app.py:142–147`),
  `PHOENIX_DISABLED` guard (`app.py:35`), span pattern (`utils.py:189–194`); `BaseRetriever.retrieve`
  auto-instruments to a RETRIEVER span.

**Live-graph measurements (this host, 2026-06-04):** §0.3 + §0.4 tables. **Benchmark:** 45 items
(T1×20/T2×10/T3×10/T4×5); all 52 `gold_sources` have `page=null` and none end in `.pdf`; 6 items are
multi-gold (T2-010, all five T4). `doc_id = sha256(raw source_url)`.
