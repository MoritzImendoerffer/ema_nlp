# Onboarding — ema_nlp

> ✅ **Post-refactor (2026-06-04).** Retrieval is LlamaIndex-first over a **Neo4j
> hierarchical `PropertyGraphIndex`** (see [`docs/RETRIEVAL.md`](RETRIEVAL.md)). The old
> Postgres + pgvector + FAISS-over-`corpus.jsonl` stack, the `EMA_RETRIEVER` switch, and
> `harness/retrieve*.py` / `harness/embed*.py` were **deleted** (LIR-012). The **benchmark +
> eval + LLM-judge + ablation + lift suite was archived** off this branch
> (`archive/pre-llamaindex-refactor`) and will be rebuilt on the Neo4j API. Where this guide
> mentions those, they are clearly flagged as **archived**.

A one-stop "where am I, what does this do, how do I run things" guide. Read this when returning to the project after time away. It complements [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) (data flow + stores), [`docs/RETRIEVAL.md`](RETRIEVAL.md) (the Neo4j retrieval pipeline), and [`docs/WORKFLOWS.md`](WORKFLOWS.md) (the workflow strategies).

---

## What this project is

A RAG benchmark over EMA (European Medicines Agency) regulatory documents. Three goals: (1) learn RAG end-to-end, (2) produce a publishable benchmark with lift metrics, (3) build a portfolio piece showing pharma + ML.

Two separable layers:

- **Retrieval** runs over the **narrative corpus** — the full PDF + HTML body text from `ema_scraper.parsed_documents` (~80k docs, EPARs included since 2026-06-02), indexed into a Neo4j `PropertyGraphIndex`. This is what the chat UI and workflows query.
- **Benchmark** is `benchmark/benchmark.jsonl` (45 curated questions) scored with the lift metric. `corpus/corpus.jsonl` (26,251 mined Q&A pairs) is benchmark/material only — it is **not** the runtime retrieval target.

---

## End-to-end data flow

```mermaid
flowchart TD
    M[(MongoDB<br/>ema_scraper.parsed_documents<br/>~80k parsed docs)] -->|python -m harness.indexing.build| N4J[(Neo4j<br/>PropertyGraphIndex<br/>:Document + :Chunk)]

    subgraph N4J_DETAIL["Neo4j graph (live full build)"]
      D[79,882 :Document]
      CH[7.4M :Chunk<br/>5.82M leaf-embedded<br/>BGE-large native vector index]
      E[HAS_CHUNK / PARENT_OF<br/>99,520 LINKS_TO]
    end

    Q[Query] --> RET[HierarchicalPGRetriever<br/>small-to-big + 1-hop LINKS_TO]
    N4J --> RET
    RET --> DOCS[ranked chunks]

    DOCS --> WF[get_workflow strategy<br/>simple_rag / crag / react / …]
    WF --> ANS[answer]

    ANS --> APP[app.py — Chainlit UI]
    APP --> PHX[(Phoenix traces<br/>localhost:6006)]
    APP -->|👍 / 👎| FB[user_rating annotation<br/>on root span]
    FB --> CACHE[FAISS query cache<br/>harness/query_cache.py]
```

`corpus.jsonl` and `benchmark.jsonl` are in Git. The Neo4j graph is **not** — it is rebuilt from Mongo by `python -m harness.indexing.build` (full GPU build over 79,882 docs; embeddings are BAAI/bge-large-en-v1.5 on local CUDA, leaf chunks only). Link extraction (`harness/indexing/links.py`) is scoped to `<main class="main-content-wrapper">` and produces typed `LINKS_TO` edges carrying `{kind, link_context, document_type, anchor}`.

---

## File map — where to look for what

| You want to... | Read / edit |
|---|---|
| Understand corpus schema | `corpus/models.py` (`QARecord`) |
| Change how docs are retrieved | `harness/indexing/property_graph.py` (`HierarchicalPGRetriever`, `open_index`) |
| Pick which retrieval setup is active | `EMA_INDEX_PROFILE` env var → `harness/configs/index/<name>.yaml` (default `neo4j_hier`) |
| Build / rebuild the Neo4j index | `python -m harness.indexing.build` (entry: `harness/indexing/build.py`) |
| Add a new index kind or retriever strategy | register via `harness/indexing/registry.py` + a new profile YAML |
| Add a new workflow strategy | `harness/workflows/<name>.py` + register in `harness/workflows/registry.py` |
| Add a new prompt variant | drop a file under `harness/prompts/` + add to `_PROMPT_FILES` in `harness/workflows/utils.py` |
| Change which model does what role | `harness/configs/models.yaml` (role-based bindings via `harness/llms.py`) |
| Chat interactively | `bash run_ui.sh` → Chainlit on :8000, Phoenix on :6006 |
| Inspect / collect feedback | Phoenix annotations (`harness/rating.py`) + Chainlit 👍/👎; cache in `harness/query_cache.py` |
| Tag docs with IDMP concepts | `python scripts/tag_concepts.py` (requires RDF in Nextcloud) |

> **Archived (on `archive/pre-llamaindex-refactor`, not on this branch):** `harness/run_eval.py`,
> `harness/embed.py`, `harness/retrieve.py`, `harness/label_session.py`, `harness/compute_lift.py`,
> the LLM-judge + ablation suite, and the FAISS-over-`corpus.jsonl` doc index. FAISS survives **only**
> as the semantic query cache (`harness/query_cache.py`).

---

## The benchmark — what's being measured

`benchmark/benchmark.jsonl` (45 questions, in Git: 20 T1 / 10 T2 / 10 T3 / 5 T4) is stratified into four difficulty tiers:

- **T1 Lookup** — single document answers it directly
- **T2 Scoping** — relevant doc is adjacent to distractors with similar vocabulary
- **T3 Multi-hop** — answer requires two cross-referenced documents
- **T4 Synthesis** — answer requires combining across multiple procedures (e.g. "compare Article 30 vs Article 31")

The headline metric is **lift**: open-book correctness minus closed-book correctness. Closed-book = same questions answered with no retrieval context. A model that memorized the corpus gets zero lift.

> **Status:** the runner that scores the benchmark (closed/open-book grids, the LLM judge, and the
> lift computation) was **archived** to `archive/pre-llamaindex-refactor` during the refactor and must
> be rebuilt on the Neo4j retrieval API before Phase 3/4 metrics run again. The benchmark items
> themselves are current and in Git. See [`project_roadmap/ABLATIONS.md`](../project_roadmap/ABLATIONS.md).

---

## Retrieval profiles — the YAML that selects retrieval

The active retrieval setup is chosen by the `EMA_INDEX_PROFILE` env var (default `neo4j_hier`), which names a file under `harness/configs/index/`. A profile describes how the index is built (`index.kind`, chunking, scope) and which retriever to attach (`retrieval.strategy`, `k`). Swapping retrieval setups is an env change, not a code edit.

Currently **one** retrieval strategy is built: `hierarchical` over `index.kind = property_graph` (profile `neo4j_hier`). The `vector_flat` / `hierarchical_links` / `property_graph_native` tracks are spec-only — see [`docs/RETRIEVAL_TRACKS.md`](RETRIEVAL_TRACKS.md).

`harness/configs/models.yaml` is separate — it defines the model catalog and role bindings. Change `roles.frontier` / `roles.mid` to swap models across **all** workflows without touching individual configs.

---

## Workflow registry — the 7 strategies

From `harness/workflows/registry.py`. See [`docs/WORKFLOWS.md`](WORKFLOWS.md) for the full how-to.

| Name | What it does |
|---|---|
| `simple_rag` | retrieve → generate (prompt variant from `prompt_strategy`: `zero_shot` / `few_shot` / `cot_self`) |
| `react` | `ReActNativeWorkflow` — hand-written think/act/observe loop; per-step Phoenix spans |
| `crag` | retrieve → grade ⇄ rewrite → generate |
| `summarize_rag` | retrieve → summarize → generate |
| `crag_summarize` | CRAG loop → summarize → generate |
| `crag_review` | CRAG loop → generate → faithfulness review |
| `react_review` | ReAct → single faithfulness review pass (score only) |

The three prompt strategies (`zero_shot`, `few_shot`, `cot_self`) apply to every workflow **except** `react` / `react_review`. The Chainlit UI flattens these 7 workflows × prompt variants into **9 display profiles** (the `_PROFILE_STRATEGY` map in `app.py`), but there are 7 underlying workflows.

`get_workflow(name, retriever=…, llm=…, prompt_strategy=…)` returns a runner with `invoke(inputs)` / `ainvoke(inputs)`. Inputs is always `{"question": str, "few_shot_context"?: str}`.

---

## HITL — the human-in-the-loop loop

```mermaid
flowchart TD
    Q[Ask a question in Chainlit] --> WF[Workflow runs]
    WF --> PHX[(Phoenix captures<br/>root + per-step spans)]
    WF --> ANS[Answer shown]

    ANS -->|Chainlit 👍 / 👎| FB[user_rating annotation<br/>on root span<br/>harness/rating.py]

    Q --> CACHE[query_cache<br/>FAISS over past queries<br/>harness/query_cache.py]
    FB --> CACHE
    CACHE -->|≥3 entries rating≥4| INJ[get_fewshot_context<br/>prepend top-k examples<br/>to system prompt]
    INJ -.-> WF
```

**Current state:**
- The Chainlit UI captures a 👍/👎 rating per answer, written as a `user_rating` annotation on the run's root span in Phoenix (`harness/rating.py`, via `_find_recent_root_span_id`).
- Phoenix + OpenInference is the trace store and labeling surface; `app.py` registers tracing via `phoenix.otel` using the `PHOENIX_URL` env var (default `http://localhost:6006`).
- `harness/query_cache.py` is a FAISS index over past query embeddings; `get_fewshot_context()` (in `harness/fewshot_inject.py`) is wired into `app.py` and injects top-k rated examples once ≥ 3 entries with rating ≥ 4 exist.

---

## Common tasks

### Start the data services

```bash
scripts/start_services.sh   # MongoDB (mongo:8.0.4) + Neo4j (neo4j:5.26 community), Docker, health-checked
```

No Postgres — it was removed by the refactor.

### Chat with the system

```bash
bash run_ui.sh                       # Phoenix (:6006) + Chainlit (:8000)
# or
PHOENIX_DISABLED=1 bash run_ui.sh    # Chainlit only, no tracing
```

Chainlit on http://localhost:8000, Phoenix on http://localhost:6006. The workflow strategy is selected per-session via the **chat-profile dropdown** (the 9 display profiles); changing it does not require a restart.

### Build / rebuild the Neo4j index

```bash
# whole corpus, GPU, fresh build (~80k docs; long-running)
python -m harness.indexing.build --full --reset --embed-device cuda

# resume an interrupted full build (no --reset — already-built docs are skipped)
python -m harness.indexing.build --full --embed-device cuda

# a 500-doc slice for quick iteration
python -m harness.indexing.build --limit 500

# rebuild only the LINKS_TO edges over an existing graph
python -m harness.indexing.build --full --reset-links
```

The active profile (`EMA_INDEX_PROFILE`, default `neo4j_hier`) decides chunking/scope/retriever. Use `--pause-every-docs` / `--pause-seconds` to throttle the GPU on long builds (the 3090 can wedge its GSP firmware under sustained load — see machine memory).

### Tag docs with IDMP concepts

```bash
python scripts/tag_concepts.py        # requires IDMP RDF in Nextcloud
```

> **Archived (off-branch):** running eval configs (`harness.run_eval`), the cross-run comparison report,
> interactive labeling (`harness.label_session`), computing lift (`harness.compute_lift`), and
> `harness.embed` no longer exist on this branch. They live on `archive/pre-llamaindex-refactor` and
> will return once the eval suite is rebuilt on the Neo4j API.

---

## What you should hold in your head

1. **One retrieval store.** Neo4j `PropertyGraphIndex` (`:Document` + `:Chunk`, `HAS_CHUNK`/`PARENT_OF`/`LINKS_TO` edges, native chunk vector index). `HierarchicalPGRetriever` walks small-to-big and expands 1 hop over `LINKS_TO`. There is no pgvector, no FAISS doc index, no `EMA_RETRIEVER` switch.
2. **Retrieval is a profile, not code.** `EMA_INDEX_PROFILE` → `harness/configs/index/<name>.yaml` selects the index kind + retriever. Today only `neo4j_hier` (hierarchical over property_graph) is built.
3. **Workflows are a registry.** `get_workflow(name, retriever=…, llm=…)` returns something with `invoke()`. Always. 7 workflows; prompt variants are a separate axis.
4. **Models are role-bound.** Code never hardcodes a model — it asks `get_llm("frontier")` / `get_llm("mid")` etc. `models.yaml` decides what those mean.
5. **Phoenix is the trace store and labeling surface.** Every LlamaIndex call is instrumented automatically (`PHOENIX_URL`); 👍/👎 annotations are the human signal.
6. **Corpus + benchmark are in Git; the graph is not.** The Neo4j graph rebuilds from Mongo `parsed_documents`. The eval/judge/lift suite is archived off-branch.

---

## Where things hurt right now

- The eval + LLM-judge + benchmark-runner + ablation + lift suite is **archived** (`archive/pre-llamaindex-refactor`); it must be rebuilt on the Neo4j retrieval API before Phase 3/4 metrics run again.
- Only one retrieval strategy is built (`neo4j_hier`); `vector_flat` / `hierarchical_links` / `property_graph_native` are spec-only (`docs/RETRIEVAL_TRACKS.md`).
- Few-shot injection needs ≥ 3 rated examples (rating ≥ 4) before it fires; the rated pool is still small.
- The 3090 can wedge its GSP firmware under sustained CUDA load — throttle long index builds with the power cap + `--pause-every-docs` (see machine memory) before any reboot.
