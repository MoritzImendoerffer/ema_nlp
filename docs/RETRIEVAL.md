# Retrieval — hierarchical PropertyGraphIndex on Neo4j

Operator's guide to the LlamaIndex-first retrieval stack introduced in the
`refactor/llamaindex-retrieval-pipeline` work (work unit
`2026-05-30_20_llamaindex-retrieval-refactor`). It replaces the former
Postgres + pgvector path (and the even older FAISS-over-`corpus.jsonl` path),
both of which are removed.

> **Refactor status (2026-06-04). Complete.** `harness/indexing/` builds a
> hierarchical `PropertyGraphIndex` in Neo4j and the `HierarchicalPGRetriever`
> returns results over the **full graph** (79,882 `:Document`, 5.82M leaf-embedded
> chunks, 99,520 `LINKS_TO` edges). The recipe engine (`harness/recipes/` → a
> `FunctionAgent`) and the chat UI (`app.py`) consume the LlamaIndex retriever
> (LIR-009/010), and the old pgvector/FAISS stack has been deleted (LIR-012). Track in
> [the work unit](../.claude/work/2026-05-30_20_llamaindex-retrieval-refactor/state.json).

---

## 1. Why Neo4j PropertyGraphIndex

The retrieval thesis is that EMA's **structure is signal**: pages link to PDFs, and
long regulatory documents have a section hierarchy. The store must represent both as
first-class edges, not metadata. A LlamaIndex `PropertyGraphIndex` backed by
`Neo4jPropertyGraphStore` holds the document/chunk graph **and** serves vector
retrieval from Neo4j's native vector index — one store, no separate vector DB.

| Need | How it's met |
|------|--------------|
| Dense chunk retrieval | Neo4j native vector index over `:Chunk(embedding)` |
| Small-to-big (leaf → parent) | `PARENT_OF` edges walked at query time |
| HTML→PDF / cross-page links | `LINKS_TO` edges between `:Document` nodes |
| Doc ↔ chunk provenance | `HAS_CHUNK` edges |
| Add another index kind later | `INDEX_REGISTRY` seam + a profile file |

Dropped, and why: **Postgres/pgvector** (a second store with hand-rolled SQL + a
recursive-CTE traversal that re-implemented what a graph store does natively);
**FAISS-over-`corpus.jsonl`** (indexed the curated Q&A surface, not the narrative
body, and leaked gold answers into eval).

---

## 2. Data + process flow

```mermaid
flowchart TD
    EMA[EMA website] -->|ema_scraper| WI["MongoDB ema_scraper.web_items<br/>(raw HTML, 115k)"]
    EMA --> PP["MongoDB ema_scraper.parsed_pdfs<br/>(PDF markdown, 65k)"]

    WI -->|trafilatura| PD["MongoDB ema_scraper.parsed_documents<br/>(parser output: url, text, content_type)"]
    PP -->|copy markdown| PD

    PD --> ING["harness.indexing.ingest.ingest(profile)<br/>= IngestedDoc IR"]
    WI -. "html_raw -> links_to" .-> ING

    subgraph BUILD["harness.indexing.build_index(profile)"]
      ING --> CH["chunk_document()<br/>hierarchical TextNodes (parents kept)"]
      CH --> TG["to_graph(): EntityNode + ChunkNode + Relation"]
      TG --> EMB["embed leaf+all chunks (bge-large, CUDA/CPU)"]
      EMB --> UP["upsert_nodes / upsert_relations<br/>+ create Chunk vector index"]
    end

    UP --> NEO[("Neo4j PropertyGraph<br/>:Document :Chunk + edges + vector index")]
    NEO --> RET["build_retriever(profile, index)<br/>HierarchicalPGRetriever"]
    RET --> WF["harness/recipes + agents — FunctionAgent (LIR-009)"]
    WF --> APP["app.py chat UI (LIR-010)"]
    APP --> PHX[MLflow traces + 👍/👎]
```

The **three Mongo collections**:

| Collection | Role | Populated by |
|------------|------|--------------|
| `web_items` | raw scrape (HTML in `html_raw`, `url` is a 1-element list) | `ema_scraper` |
| `parsed_pdfs` | pymupdf4llm PDF markdown (`_id` = url, `markdown`, `error`) | `scripts/ingest_parsed_pdfs.py` |
| `parsed_documents` | canonical parser output (`url, parser, parser_version, content_type, text, text_format, error`) | parsers / `scripts/backfill_parsed_documents_subset.py` |

> **Data note.** `parsed_documents` holds the full ~80k-doc parser output and the Neo4j
> index (79,882 `:Document`) was built from it. The old `link_graph` collection was never
> built — links are extracted at ingest from `web_items.html_raw` by `harness.indexing.links`.
> `scripts/backfill_parsed_documents_subset.py` seeds a small coherent verify subset
> (HTML pages + the PDFs they link to) for quick CPU iteration.

---

## 3. The node / graph model

```mermaid
flowchart LR
    D1["(:Document) page A<br/>id=sha256(url), title, committee, topic_path"]
    D2["(:Document) PDF B"]
    C0["(:Chunk) root"]
    C1["(:Chunk) mid"]
    C2["(:Chunk) leaf (embedded)"]

    D1 -- HAS_CHUNK --> C0
    C0 -- PARENT_OF --> C1
    C1 -- PARENT_OF --> C2
    D1 -- LINKS_TO --> D2
```

- **`:Document`** entity node per web page / PDF — `id = sha256(source_url)`, with
  `title`, `committee`, `topic_path`, `reference_number`, `source_type`.
- **`:Chunk`** node per hierarchical chunk — `id`, `text`, `is_leaf`, `doc_id`,
  `source_url`, `embedding`. Multi-level (chunk_sizes `[2048,512,128]`); parent/child
  retained (the old flat chunker discarded non-leaves).
- **Edges:** `HAS_CHUNK` (doc→chunk), `PARENT_OF` (chunk→chunk), `LINKS_TO`
  (doc→doc, only when the target is in the corpus; carries `{kind, link_context,
  document_type, anchor}` properties since the 2026-06-04 link-extraction upgrade —
  99,520 main-content-scoped edges, see `docs/RETRIEVAL_TRACKS.md` §0.8). Edge set is
  extensible (typed concepts later) without reshaping the pipeline.

---

## 4. Configuration — profiles + env var

Which index/retriever is active is chosen by **`EMA_INDEX_PROFILE`** (default
`neo4j_hier`) → `harness/configs/index/<name>.yaml`. Credentials are **not** in the
profile — they come from the environment.

`harness/configs/index/neo4j_hier.yaml`:

```yaml
index:
  kind: property_graph              # only kind in v1 (INDEX_REGISTRY seam allows more)
  source: mongo_parsed_documents
  embed_model: BAAI/bge-large-en-v1.5
  store: { graph: neo4j }           # holds nodes/edges AND the chunk vector index
  chunking: { parser: hierarchical, chunk_sizes: [2048, 512, 128] }
  scope: { committee: [], topic_prefix: "", limit: 50 }   # subset-first
retrieval:
  strategy: hierarchical            # small-to-big merge + links_to traversal
  k: 10
  merge: true
  graph: { max_hops: 1, edge_types: [links_to] }
```

Env (`~/.myenvs/ema_nlp.env`):

```bash
NEO4J_URI=bolt://localhost:7687        # bolt://localhost:7688 if coexisting with a native Neo4j
NEO4J_USER=neo4j
NEO4J_PASSWORD=ema_nlp_dev_pw          # >= 8 chars (Neo4j 5.x)
EMA_INDEX_PROFILE=neo4j_hier           # optional; this is the default
```

---

## 5. Code map (`harness/indexing/`)

| Module | Responsibility |
|--------|----------------|
| `profiles.py` | profile schema + `load_index_profile()` (env/explicit/default) |
| `registry.py` | `INDEX_REGISTRY` / `RETRIEVER_REGISTRY` + `build_index` / `build_retriever` dispatch + `@register_*` decorators |
| `chunking.py` | `chunk_document()` — hierarchical TextNodes, parents kept, deterministic ids |
| `links.py` | `extract_links()` — typed `links_to` edges from a page's `main-content-wrapper` (ported from `ema_scraper` `EmaPageParser`; BCL-component aware). Each carries `kind` (file/page/external) **and** `link_context` (file_component/card_or_listing/inline/other) + `document_type`. See `docs/RETRIEVAL_TRACKS.md` §0.8. |
| `ingest.py` | `ingest(profile)` — Mongo `parsed_documents` → `IngestedDoc` IR (entity + chunks + links) |
| `property_graph.py` | `build_property_graph_index()` + `HierarchicalPGRetriever` (registered `property_graph` / `hierarchical`) |

---

## 6. Build + retrieve

```bash
scripts/start_services.sh        # Mongo + Neo4j (Docker), health-checked
```

```python
from harness.indexing import load_index_profile, build_index, build_retriever

profile  = load_index_profile()                 # EMA_INDEX_PROFILE or neo4j_hier
index    = build_index(profile, reset=True)     # embed chunks -> Neo4j + chunk vector index
retriever = build_retriever(profile, index)     # HierarchicalPGRetriever
nodes = retriever.retrieve("nitrosamine acceptable intake limit")
# -> list[NodeWithScore]; node.metadata has source_url, doc_id, matched_chunk
```

### Retrieval at query time

```mermaid
sequenceDiagram
    participant Q as query
    participant E as bge-large
    participant N as Neo4j
    Q->>E: embed(query)
    E->>N: db.index.vector.queryNodes(chunk index, k, qvec)
    N-->>N: expand HAS_CHUNK (->doc) + PARENT_OF (->parent)
    N-->>Q: NodeWithScore[] (parent text when merge=true, + source_url)
```

`HierarchicalPGRetriever` queries the dedicated `:Chunk` vector index (Neo4j's
auto-created `entity` index only covers `:__Entity__`, so chunks need their own),
then in **one Cypher** expands `HAS_CHUNK`→doc and `PARENT_OF`→parent, returning the
**parent** chunk when `merge=true` (small-to-big), deduped, with `source_url`/`doc_id`.

> **Throughput.** CPU embedding is ~0.7 s/chunk (≈17 min for the 40-doc/1462-chunk
> subset). Run the full build on the GPU host (`torch.cuda` available there); CPU is
> fine for small verify slices.

---

## 7. Adding another index kind

The registry is the seam (mirrors the `harness/tools/registry.py` decorator pattern):

1. Write a builder and register it:
   ```python
   from harness.indexing.registry import register_index, register_retriever

   @register_index("faiss_flat")
   def build_faiss(profile, **kw): ...

   @register_retriever("vector")
   def build_vector_retriever(profile, index, **kw): ...
   ```
2. Import the module in `harness/indexing/__init__.py` (so the decorators run).
3. Add a profile `harness/configs/index/<name>.yaml` with `index.kind: faiss_flat`.
4. Select it with `EMA_INDEX_PROFILE=<name>`. No workflow/UI/tracing changes.

---

## 8. Tests

```bash
pytest tests/test_indexing_profiles.py tests/test_indexing_chunking.py \
       tests/test_indexing_links.py tests/test_indexing_ingest.py \
       tests/test_indexing_property_graph.py        # 36 tests, no infra (mongomock)
```

The live build + retrieval are integration-verified against Neo4j (not in CI).

---

## 9. Troubleshooting

**Container can't bind `:7474`/`:7687`.** A native Neo4j already holds them. Run the
project container on alt ports (`NEO4J_HTTP_PORT=7475 NEO4J_BOLT_PORT=7688 docker
compose -f deploy/neo4j/docker-compose.yml up -d`) and set `NEO4J_URI=bolt://localhost:7688`.

**Retrieval returns 0 nodes.** The `:Chunk` vector index is missing — `build_index`
creates it (`ensure_chunk_vector_index`); confirm with `SHOW VECTOR INDEXES`.

**`Could not load OpenAI model` during `from_existing`.** `kg_extractors=[]` falls back
to an LLM extractor; the build passes `llm=MockLLM()` to avoid it. Use
`property_graph.open_index()` to open the store without rebuilding.

**Mongo unreachable / `parsed_documents` empty.** Bring up Mongo
(`scripts/start_services.sh`); seed the verify subset with
`scripts/backfill_parsed_documents_subset.py`.
