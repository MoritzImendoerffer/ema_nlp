# Exploration: Agentic memory, document trees, and transparency

**Date:** 2026-05-15  
**Phase context:** Phase 1 in progress (extractors built). TASK-016 (embedding + vector store) is the next Claude task — this exploration should inform that design before it is built.

---

## What the user is asking about

Three interconnected concerns:

1. **Agentic memory** — agents in multi-hop retrieval rediscover information on every query because they have no persistent memory across retrieval steps. The user points to the PageIndex/LlamaIndex document-tree approach as a model: build hierarchical summaries upfront so the agent has a "map" of the corpus and can navigate rather than search blindly.

2. **Transparency** — every query must produce a reproducible, inspectable trace of how the agent retrieved, reranked, and interpreted information. OlmoTrace (OLMo-specific) is already in the roadmap; the requirement here is model-agnostic tracing that works regardless of which LLM is used.

3. **Extensibility** — start with simple flat RAG; but the architecture should make it possible to add richer document understanding (tables, images, structure-aware chunking) without a rewrite.

---

## Where this sits in the existing roadmap

The roadmap already defers graph/ontology to v2+ (correct decision for v1). But some of what the user describes is different from full graph-RAG:

| Concept | What the roadmap says | What this exploration adds |
|---------|----------------------|---------------------------|
| Vector retrieval (TASK-016) | FAISS flat index, BGE-large | Replace with LlamaIndex VectorStoreIndex — identical capability, adds composability |
| ReAct agent (TASK-027) | Custom implementation | Use LlamaIndex `ReActAgent` — existing library, built-in step tracing |
| Tracing | Not yet designed | OpenInference + Arize Phoenix from session 1 — model-agnostic |
| Document hierarchy | Not in schema | Add parent/child relationships in the LlamaIndex node layer, not in corpus.jsonl |
| Ontology (IDMP) | Deferred to v2+ | Use as node metadata only — no graph, no Neo4j |

The key insight is: **adopting LlamaIndex as the retrieval framework (instead of raw FAISS + custom code) unlocks all three concerns with minimal added complexity**, because the library already provides document trees, agent tracing, and composable pipelines.

---

## Architecture recommendation: layered, not built all at once

### Layer 0 — Already built (Phase 1)
`corpus.jsonl` with Q&A records and `cross_refs`. This stays exactly as-is. All layers above read from this file.

### Layer 1 — Document tree index (build at TASK-016)

Instead of raw FAISS, build a **`DocumentSummaryIndex`** in LlamaIndex:

```
EMA Document (root node, summary auto-generated)
  ├── Q&A pair 1 (leaf node, full text embedded)
  ├── Q&A pair 2 (leaf node)
  │     └── cross_ref → Q&A pair 7   ← relationship, not a copy
  └── Q&A pair N
```

What this gives:
- **Agentic memory**: the agent can retrieve a document-level summary first to decide whether to drill into a document, rather than embedding-searching every Q&A pair cold
- **Not all docs need embeddings upfront** — exactly the PageIndex approach the user mentions. Summary nodes are cheap to retrieve; leaf embeddings are only built for docs that get queried
- **Cross-refs become node relationships** (PARENT, CHILD, RELATED) using LlamaIndex's built-in `NodeRelationship` type — no ontology or graph DB needed

Implementation is a thin wrapper around the existing corpus reader:

```python
from llama_index.core import DocumentSummaryIndex, SimpleDirectoryReader
from llama_index.core.schema import TextNode, NodeRelationship, RelatedNodeInfo

# Build nodes from corpus.jsonl, add relationships from cross_refs field
# Persist index to disk → agents reuse without rebuilding
```

Persistence: the index serialises to a local directory (or FAISS + JSON). No new database required for v1.

### Layer 2 — Transparent agent (TASK-027, Ablation B)

Use LlamaIndex `ReActAgent` with the four tools already specified in ABLATIONS.md:

```python
tools = [search_tool, follow_cross_refs_tool, filter_by_topic_tool, answer_tool]
agent = ReActAgent.from_tools(tools, llm=llm, verbose=True)
```

Every agent step (thought → action → observation) is a first-class object, inspectable as JSON. The agent already produces what the user calls "reasoning chains."

Trace each run with **OpenInference instrumentation** (see Layer 3). This is model-agnostic — it instruments at the LlamaIndex framework level, not at the OpenAI/Anthropic API level.

### Layer 3 — Model-agnostic tracing (add at TASK-020, before first baseline run)

**Arize Phoenix** is the right tool here:
- Free, open-source, self-hosted (no cloud account needed)
- Works with LlamaIndex, LangChain, raw OpenAI/Anthropic calls via OpenInference
- Saves traces as JSONL — fits the `results/<run_id>/` paradigm already in the roadmap
- UI shows every retrieval step, reranking decision, LLM call, and token count
- Each span has: input, output, latency, model, and the full retrieval context

Integration is a one-line import at the top of `run_eval.py`:

```python
import phoenix as px
from openinference.instrumentation.llama_index import LlamaIndexInstrumentor

px.launch_app()  # starts local Phoenix server
LlamaIndexInstrumentor().instrument()
# everything below this line is automatically traced
```

Per-query, this produces a trace tree like:
```
query("What AI limit applies during CAPA?")
  ├── retrieve(query, k=5) → [qa_022, qa_020, qa_010]
  │     ├── embed_query → vector
  │     └── faiss_search → [(qa_022, 0.92), ...]
  ├── rerank([qa_022, qa_020, qa_010]) → [qa_020, qa_022, qa_010]
  └── generate(context, question) → answer + cited_ids
```

Traces can be exported as JSONL and committed alongside results — satisfying the reproducibility requirement. This replaces OlmoTrace as the **default** tracing tool (OlmoTrace is OLMo-specific; Phoenix works for all models).

### Layer 4 — Ontology as metadata (optional, add if benchmark shows benefit)

The IDMP RDF files are already at `~/Nextcloud/Datasets/Pistoia-Alliance-Ontologies/`. Rather than building a graph:

1. Parse the RDF to extract ~50–100 key regulatory concepts (substance, indication, MAH, product, procedure type)
2. At corpus build time, tag each Q&A record with matching concepts (simple string matching or lightweight NER)
3. Store as `metadata["concepts"]: ["nitrosamine", "chronic-use", "CAPA"]` on each LlamaIndex node
4. Use metadata filters in retrieval: `filter_by_topic(topic_path)` becomes `filter_by_concept(concept)`

This is **not ontology-based reasoning** — it's just structured filtering. But it's the right foundation: if a benchmark failure later justifies adding full entity linking or PropertyGraphIndex, the metadata is already there as the seed.

### Layer 5 — Rich document understanding (deferred, but not locked out)

For documents with tables and images (Phase 1 already handles PDF Q&As via PyMuPDF4LLM):

LlamaIndex has `SimpleDirectoryReader` with multimodal parsers and `MarkdownElementNodeParser` that preserves table structure. These can be dropped into the node-building pipeline at TASK-016 without changing the agent or evaluation harness.

Roadmap impact: zero. The existing TASK-006 (PDF extractor) already uses PyMuPDF4LLM. Layer 5 is a config change in the document loader, not a new architecture.

---

## What doesn't change

- `corpus.jsonl` schema — unchanged. The LlamaIndex index is built *from* the corpus, not instead of it.
- The five evaluation metrics — unchanged.
- The ablation designs (A, B, C) — unchanged. The agent in Ablation B becomes a LlamaIndex `ReActAgent`, which is exactly what was already planned.
- The config-as-code principle — Phoenix traces are just another artifact in `results/<run_id>/`.

---

## Strategy decision: LlamaIndex or LangChain?

Both are viable. The recommendation here is **LlamaIndex** because:

1. Its `DocumentSummaryIndex` is a direct match for the PageIndex approach the user describes
2. `NodeRelationship` natively models the `cross_refs` in the EMA corpus schema
3. `ReActAgent` with step tracing is already the architecture for Ablation B
4. OpenInference instrumentation for LlamaIndex is actively maintained by Arize
5. The roadmap already mentions FAISS and sentence-transformers — LlamaIndex wraps both

LangChain is a better choice if the project were primarily prompt-chain-centric. This project is retrieval-centric with structured document relationships — LlamaIndex wins on that axis.

---

## What Graph-RAG adds (and why it stays deferred)

Graph-RAG (Microsoft, 2024) builds a knowledge graph of entity relationships from the full corpus, then uses community summaries for global questions. It's powerful for questions like "which Q&A documents are most central to nitrosamine regulation?" but adds significant complexity:

- Requires an LLM pass over the full corpus to extract entity relationships (expensive)
- Requires a graph DB (Neo4j) or in-memory graph
- Community detection (Leiden algorithm) is an additional dependency

The `cross_refs` in the EMA corpus are already a hand-authored knowledge graph — the documents' own authors marked the relationships. This is arguably *better* than entity extraction from text. LlamaIndex's `NodeRelationship` captures this without a graph DB.

Graph-RAG should be revisited after Ablation B, specifically if the T3 (multi-hop) results show the `follow_cross_refs` tool is insufficient even when used correctly.

---

## Concrete changes to the implementation plan

These modify existing tasks without adding phases:

| Task | Change |
|------|--------|
| TASK-016 | Build `DocumentSummaryIndex` (LlamaIndex) instead of raw FAISS. Persist to `harness/index/`. Add `python-llama-index` to pyproject.toml. |
| TASK-017 | BM25 retrieval stays; use LlamaIndex's `BM25Retriever` wrapper for composability |
| TASK-019 | Add Phoenix instrumentation to `run_eval.py` before first baseline run |
| TASK-020 | Save Phoenix trace export (JSONL) alongside config+results in `results/<run_id>/traces.jsonl` |
| TASK-027 | Use `ReActAgent` from LlamaIndex rather than custom ReAct. Tools are identical; the agent loop is library-managed |

One new half-task:

| Task | Description | Effort |
|------|-------------|--------|
| TASK-016.5 | Add `concepts` metadata to corpus nodes from IDMP ontology concepts (simple string matching, no graph) | 2h |

---

## Libraries to add to pyproject.toml

```toml
"llama-index-core>=0.10",
"llama-index-vector-stores-faiss>=0.1",
"llama-index-retrievers-bm25>=0.1",
"arize-phoenix>=4.0",
"openinference-instrumentation-llama-index>=2.0",
```

The existing `faiss-cpu`, `sentence-transformers`, and `rank-bm25` stay — LlamaIndex uses them as backends.

---

## Risk: LlamaIndex API churn

LlamaIndex has a history of breaking API changes (the 0.8→0.10 rewrite was significant). Mitigation: pin to a specific minor version and review release notes before upgrading. The abstraction cost is worth it for the composability and tracing it provides.

---

## Summary of recommendations

| Concern | Recommendation | Complexity | When |
|---------|---------------|------------|------|
| Agentic memory / document tree | LlamaIndex `DocumentSummaryIndex` | Low | TASK-016 |
| Cross-ref relationships | `NodeRelationship` on existing `cross_refs` field | Low | TASK-016 |
| Model-agnostic tracing | Arize Phoenix + OpenInference | Low (one import) | TASK-020 |
| Extensible agent | LlamaIndex `ReActAgent` | Low | TASK-027 |
| Ontology as metadata | IDMP concept tags on nodes | Low-medium | TASK-016.5 |
| Rich doc understanding (tables/images) | LlamaIndex multimodal parsers | Deferred | After v1 |
| Graph-RAG | Defer | — | Only if T3 fails after Ablation B |
