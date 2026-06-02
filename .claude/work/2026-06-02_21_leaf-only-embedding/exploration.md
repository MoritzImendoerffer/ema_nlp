# Exploration — "all 3 hierarchical levels are being embedded, not just leaves"

**Question (user):** Is this a bug in our code, or a behaviour of the chosen text splitter?
**Answer:** It is a **bug in our build code.** The splitter (`HierarchicalNodeParser`)
emitting all three levels is **correct and intended** — that hierarchy is exactly what
small‑to‑big retrieval needs. Our build then *embeds every level* instead of restricting
embedding to the leaf chunks, which is the deviation.

---

## 1. What the splitter does (correct, by design)

`harness/indexing/chunking.py::chunk_document` builds
`HierarchicalNodeParser.from_defaults(chunk_sizes=[2048, 512, 128])` and returns
**all** nodes it produces. Verified against the installed LlamaIndex:

```
HierarchicalNodeParser.from_defaults(chunk_sizes=[2048,512,128]) →
  level parser chunk_size_2048: SentenceSplitter chunk_size=2048 overlap=20
  level parser chunk_size_512 : SentenceSplitter chunk_size=512  overlap=20
  level parser chunk_size_128 : SentenceSplitter chunk_size=128  overlap=20

sample doc → total nodes: 225 | levels: {root: 9, mid: 42, leaf: 174} |
             get_leaf_nodes(): 174 | get_root_nodes(): 9 | leaf fraction 0.77
```

- `chunk_size` is in **tokens** (not chars); leaf = 128 tokens, overlap = 20 (standard).
- The parser **emits every level** with `PARENT`/`CHILD` relationships. This is the
  documented contract and is required for AutoMerging / small‑to‑big retrieval — you must
  keep the parents so you can merge a matched leaf up to a larger context.
- LlamaIndex ships `get_leaf_nodes(nodes)` precisely because the *canonical* pattern is:
  **index (embed) the leaves only**, keep parents in the store, and reach parents by id
  via the child→parent relationship at query time. Our chunker already mirrors this intent:
  it stamps `is_leaf` and exposes a `leaf_nodes()` helper, and its docstring says
  *"leaf chunks flagged is_leaf=True (those are what LIR‑007 embeds)."*

So: **the splitter is doing the right thing.** Producing all levels is not over‑splitting
and not a bug.

## 2. Where our code goes wrong (the actual bug)

`harness/indexing/property_graph.py`:

- `_chunk_nodes_and_rels(d)` iterates **`for cn in d.chunk_nodes`** (= *all* levels) and
  turns each into a `ChunkNode` (correct — we *want* all levels stored, with
  `HAS_CHUNK` + `PARENT_OF`). It stamps `is_leaf` into each ChunkNode's properties.
- `_embed_pass.flush()` then embeds **everything**:
  ```python
  embs = embed.get_text_embedding_batch([c.text for c in chs])  # chs = ALL levels
  for c, e in zip(chs, embs): c.embedding = e
  store.upsert_nodes(ents + chs)                                  # every node gets a vector
  ```
  There is **no `is_leaf` filter.** Every 2048/512/128‑token node is embedded and written.

The vector index is `CREATE VECTOR INDEX ema_chunk_embedding FOR (c:Chunk) ON (c.embedding)`.
Neo4j only indexes nodes that *have* the property, so today — because we set `embedding`
on every node — the index contains all three levels.

**Live confirmation on the in‑progress graph:**

```
total chunks            : 1,285,159
leaf  (is_leaf=true)    : 1,016,047  (79%)
non‑leaf (is_leaf=false):   269,112  (21%)
chunks WITH NO embedding:         0      ← every level is embedded
non‑leaf WITH embedding :   274,968      ← all parents embedded
```

The production leaf fraction (79%) matches the splitter's structural ratio
(2048:512:128 = 16:4:1 ⇒ ~76% leaves), so nothing anomalous is happening in the
hierarchy itself — we are simply embedding the ~21% of nodes we shouldn't.

**Verdict:** not the splitter; a missing leaf filter in `_embed_pass`/`_chunk_nodes_and_rels`.
The behaviour contradicts our own chunker docstring, the unused `leaf_nodes()` helper, and
the LIR‑008 spike note ("vector search on **leaf chunks** → merge up").

## 3. Consequences

### A. Retrieval quality (the serious one)
The retriever (`HierarchicalPGRetriever._QUERY`) does
`db.index.vector.queryNodes(ema_chunk_embedding, k, q)` over the **mixed‑granularity** pool,
then unconditionally merges up: *"if the hit has a `PARENT_OF` parent, return the parent."*

With all levels in the index:
- **Inconsistent / oversized context.** A leaf hit → returns its 512‑token parent (intended).
  But a 512 hit → returns its **2048** parent; a 2048 (root) hit → returns **itself (2048)**.
  So top‑k mixes 512‑ and 2048‑token blocks; "small‑to‑big" stops being small‑to‑*one‑step*‑big.
- **Redundancy burns the k budget.** Parent text *contains* child text. The index can return
  a parent and its own descendant, or several siblings plus their parent, as separate hits.
  Id‑dedup only catches the case where two hits merge to the *same* parent id; it does **not**
  remove a 2048 root that overlaps a 512 hit from elsewhere in the same doc. Fewer *distinct*
  regions per query ⇒ worse coverage for multi‑hop (T3) and scoping (T2).
- **Precision loss / score skew.** A 2048‑token embedding is an averaged, "blurry" vector; for
  precise lookups (T1) it can outrank the focused 128→512 chunk that actually answers the
  question, dragging a wall of text into the LLM context. Scores across granularities aren't
  comparable, so top‑k ranking is distorted. The intended design embeds a **uniform** leaf
  space and derives context by a *controlled* one‑step merge‑up — embedding parents
  short‑circuits that control.

### B. Compute (wasted GPU time)
~21% of all embeddings are parents the retriever never matches against (parents are fetched
by graph traversal, by id — never by vector similarity). On the throttled ~51 ch/s run that
is ~1/5 of a multi‑day job spent embedding vectors that are pure waste.

### C. Storage / index size
bge‑large = 1024 × float32 = 4 KB/vector. ~269k surplus parent vectors ≈ **~1.1 GB** of extra
embeddings on nodes + a 21%‑larger native vector index ⇒ more RAM and marginally slower ANN
queries.

### D. Design/docs drift
Implemented behaviour ("embed all levels") contradicts the documented design
("vector search on leaf chunks"). Anyone reasoning from `docs/RETRIEVAL.md` or the chunker
docstring is misled.

> Note: this is **independent** of the EPAR‑scope finding (22.7% of docs are out‑of‑scope
> EPAR assessment reports). The leaf‑only fix is correct regardless of how the EPAR question
> is resolved; the two compound (EPARs are the largest docs, so they also carry the most
> surplus parent vectors).

## 4. Fix (small, localised)

Embed **leaves only**; keep storing parents (text + `PARENT_OF`) so merge‑up still works —
parents simply carry no `embedding`, so Neo4j auto‑excludes them from the vector index.

`_embed_pass.flush()` (sketch):
```python
leaves = [c for c in chs if c.properties.get("is_leaf")]
if leaves:
    embs = embed.get_text_embedding_batch([c.text for c in leaves])
    for c, e in zip(leaves, embs):
        c.embedding = e
    if not vindex["done"]:
        ensure_chunk_vector_index(store, len(embs[0]))   # size from a LEAF vector
        vindex["done"] = True
store.upsert_nodes(ents + chs)   # parents upserted WITHOUT embedding
```
(`ensure_chunk_vector_index` currently keys off `chs[0].embedding`; after the fix `chs[0]`
may be a parent with no embedding, so trigger off the leaf set instead.)

### Remediating the already‑built graph (no re‑embed needed)
The leaves already have *correct* embeddings; only the parents are surplus. If we keep the
current graph we can drop the surplus vectors in one cheap statement (Neo4j removes them from
the index automatically — no re‑embedding):
```cypher
MATCH (c:Chunk {is_leaf:false}) WHERE c.embedding IS NOT NULL REMOVE c.embedding
```
This is safe: the retriever reads parent **text** (`p.text`), never `p.embedding`.
Caveat: the *running* build keeps writing parent vectors for new docs, so either (a) land the
code fix and `--reset` rebuild, or (b) land the code fix, let the run finish, then run the
REMOVE sweep once. The EPAR‑scope decision likely forces a `--reset` rebuild anyway, which
supersedes the sweep.

## 4a. External corroboration (NVIDIA GenerativeAIExamples)

NVIDIA's LlamaIndex hierarchical-node-parser example
(`nvidia.github.io/GenerativeAIExamples/0.5.0/notebooks/04_llamaindex_hier_node_parser.html`)
is the canonical pattern and does exactly leaf-only indexing:
```python
return nodes, get_leaf_nodes(nodes)                       # all-nodes vs leaves
docstore.add_documents(nodes)                             # ALL levels -> docstore (unembedded)
index = VectorStoreIndex(leaf_nodes, storage_context=...) # ONLY leaves embedded/indexed
retriever = AutoMergingRetriever(index.as_retriever(similarity_top_k=12), storage_context=...)
```
Maps onto our Neo4j model as: **leaves carry `embedding` (→ vector index); parent `:Chunk`
nodes are the docstore equivalent — stored with text, no `embedding`** and reached via
`PARENT_OF`. We intentionally use a custom `HierarchicalPGRetriever` + `PARENT_OF` instead of
the docstore + `AutoMergingRetriever` (LIR-008 spike: native AutoMerging needs a LlamaIndex
docstore we don't keep). Note one *separate* behavioural gap: `AutoMergingRetriever` merges
only when enough of a parent's children are retrieved (ratio-gated); our retriever merges on
any leaf hit (unconditional) — a retriever-tuning question, independent of this embedding fix.

## 5. Key files
- `harness/indexing/property_graph.py` — `_embed_pass.flush()`, `_chunk_nodes_and_rels()`,
  `ensure_chunk_vector_index()`, `HierarchicalPGRetriever._QUERY` (read‑only; confirms parents
  are reached by traversal, not vector).
- `harness/indexing/chunking.py` — `chunk_document()` (all levels, correct), `leaf_nodes()`
  + `is_leaf` (the intended filter, currently unused by the build).
- `harness/configs/index/neo4j_hier.yaml` — `chunk_sizes: [2048, 512, 128]`.
- Tests: `tests/test_indexing_property_graph.py` (extend with a leaf‑only‑embedding assertion).
