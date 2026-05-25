# Session decisions — 2026-05-25

Resolves the three open items that were ambiguous after planning so a
fresh session can execute without re-deriving them. Cross-refs to
`requirements.md`, `implementation-plan.md`, `state.json`.

---

## 1. Postgres install path → Docker Compose (resolves NARR-001 + plan §240)

`implementation-plan.md` line 240 listed "apt vs. Docker" as an open
assumption. Locked: **Docker Compose**, under `deploy/postgres/`.

**Rationale**
- Docker is already installed on `schleppi` (`Docker version 29.1.3`,
  `Compose 2.40.3`). Postgres is not.
- Sandboxed: `docker compose down -v` is a clean rollback; no system
  Postgres install on the dev host.
- Same image works on the 3090 PC for the GPU-side ingest, so the
  schema + data volume can be reproduced identically there.

**Concrete spec for NARR-001**
- Image: `pgvector/pgvector:pg16` (official; ships pgvector ≥ 0.7
  built in — exceeds the ≥ 0.5.0 HNSW requirement in NARR-001 AC).
- File: `deploy/postgres/docker-compose.yml` with:
  - port `5432:5432` (override if collision)
  - named volume `ema_nlp_pgdata` mounted at `/var/lib/postgresql/data`
  - env: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB=ema_nlp`
- File: `deploy/postgres/README.md` documenting `docker compose up -d`,
  `pg_isready` check, and the `~/.myenvs/ema_nlp.env` sample line:
  `PG_DSN=postgresql://ema_nlp:CHANGEME@localhost:5432/ema_nlp`
- `apt` install path is *not* documented as an alternative — keep one
  path supported to avoid drift.

---

## 2. Two-machine execution split (new — not in original plan)

The work unit was written assuming a single host. In reality two
machines are involved:

| Machine    | Has GPU? | Has Postgres? | Has MongoDB? | Role |
|------------|----------|---------------|--------------|------|
| `schleppi` (laptop)  | no   | not yet (use Docker) | yes (`localhost:27017`, ping=ok) | Code-side: write modules + unit tests, bring up Postgres via Docker, run init_db, run pure-Python tests |
| 3090 PC    | yes (NVIDIA 3090) | TBD (use same Docker compose) | TBD     | Run BGE embedder, run real ingest, run timing benchmarks, run E2E smoke |

### Tasks executable on `schleppi`

Code is written and committed; tests that need no GPU or live data run
locally. These tasks reach **code-complete** on the laptop:

```
NARR-001 NARR-002 NARR-003 NARR-004 NARR-005 NARR-006* NARR-009
NARR-012 NARR-015 NARR-016† NARR-017† NARR-018 NARR-019† NARR-020*
NARR-021 NARR-022* NARR-024 NARR-025 NARR-026† NARR-027
```

- `*` = code lands; the smoke test in its AC is deferred to the 3090 PC
  (BGE on GPU, real ReAct run, Phoenix eval slice).
- `†` = test against a tiny seeded fixture DB on `schleppi` is fine;
  full-corpus validation still happens on the 3090 PC.

### Tasks the 3090 PC must run

These have a *runtime* gate that requires the GPU or a populated DB:

```
NARR-006 GPU smoke (encode batch of 8)
NARR-007 limit-10 ingest of parsed_pdfs (real BGE on GPU)
NARR-008 resume + --force verification on the same slice
NARR-010 limit-10 ingest of HTML web_items
NARR-011 timing notes (--limit 100 PDFs + 100 HTML)
NARR-013 link-graph row counts after ingest
NARR-014 resolve_links.py run + resolution-rate report
NARR-022 5-question eval slice under both backends
NARR-023 simple_rag E2E on 5 benchmark questions
NARR-028 switch default EMA_RETRIEVER → pgvector
```

### Handoff protocol

1. **Schleppi** finishes all code-side tasks → single commit on `main`
   with the addendum + state.json updates → `git push`.
2. On the 3090 PC: `git pull && uv pip install -e ".[dev]"`,
   `docker compose -f deploy/postgres/docker-compose.yml up -d`,
   `python scripts/init_db.py`, then run the runtime-gated tasks in
   the order listed above.
3. Each runtime-gated task updates `state.json` and appends one row to
   `.claude/HISTORY.md` per the CLAUDE.md convention.

**Why this split**: BGE-large-en-v1.5 on CPU embeds ~1 chunk/sec on
the laptop; even a limit-10 PDF run is multi-minute and proves nothing
that a GPU run won't. Better to mark the boundary explicitly than to
half-run things on CPU.

---

## 3. Existing-code patterns the pgvector path MUST mirror

Phase E is "drop-in replacement of `harness/retrieve.py`". For that to
work, the new code must match the existing public shape. These are the
load-bearing patterns confirmed by reading the current codebase.

### From `harness/retrieve.py`

- **Result tuple shape — UNCHANGED**:
  ```python
  RetrievalResult = tuple[str, float, dict]   # (id, score, metadata)
  ```
  For pgvector the `id` is `chunk_id`, score is `1 - cosine_distance`
  (higher = better, matching dense / RRF semantics). Metadata dict
  must at minimum carry `source_url`, `source_type`, `topic_path`,
  `reference_number`, `committee`, `heading_path`, `doc_id`,
  `chunk_id`. Workflows treat `meta["cross_refs"]` today; for the PG
  path, that key becomes the list of resolved `tgt_doc_id`s from the
  `links` table joined per chunk (so the recursive strategy in
  `_retrieve_recursive` keeps working unchanged).

- **Config dataclass + `from_yaml_section` classmethod — REQUIRED**:
  Mirror `RetrievalConfig.from_yaml_section`. `RetrievalConfigPG` adds
  `prefilter: PrefilterConfig` and `traversal: TraversalConfig`
  sub-dataclasses, parsed the same way (sub-dict → sub-dataclass).

- **RRF constant — UNCHANGED**:
  ```python
  _RRF_K = 60   # do NOT pick a different K in retrieve_pg.py
  ```
  Reuse the existing `_rrf_fuse(ranked_lists, k)` algorithm verbatim;
  it operates on result tuples so it is store-agnostic.

- **Factory layering — UNCHANGED**:
  ```python
  build_retrieve_fn(ret_config, abl_config, index, hier_index=None)
      -> Callable[[str], list[RetrievalResult]]
  ```
  The returned callable carries `retrieve_fn.ablation_config` so
  workflows can read it via `config_attributes()`. `build_retrieve_fn_pg`
  must expose the same signature **and** the same `.ablation_config`
  attribute. The A1/A2/A3/A4 ablation wrappers (query expansion, topic
  filter, reranker) sit OUTSIDE the retriever and must keep working —
  do not duplicate that stack inside the PG module; reuse the existing
  one.

- **`hier_index` parameter**: not applicable to pgvector. The
  signature accepts it for symmetry but `build_retrieve_fn_pg` raises
  if `ret_config.strategy == "hierarchical"` (hierarchical is a
  FAISS-only feature for v1).

### From `harness/embed.py`

- **Embedding constants — REUSE, do not re-declare**:
  ```python
  EMBED_MODEL_NAME = "BAAI/bge-large-en-v1.5"   # imported from harness.embed
  EMBED_DIM = 1024
  ```
  `harness/embed_pg.py` should import these to keep the FAISS path and
  the PG path embedded with the same model.

- **`providers.configure_embed_model()` is the single embed entrypoint**:
  NARR-006 says "uses `harness/providers.py` to configure BGE via
  LlamaIndex Settings." Concretely:
  ```python
  from harness.providers import configure_embed_model
  configure_embed_model()                # honours EMA_EMBED_MODEL env
  from llama_index.core.settings import Settings
  vectors = Settings.embed_model.get_text_embedding_batch(texts)
  ```
  Do NOT instantiate `HuggingFaceEmbedding` directly in `embed_pg.py`;
  that would split the env-var contract.

- **`get_node_by_id` shape**: `harness/embed.py:159` exposes
  `get_node_by_id(index, qa_id) -> TextNode | None`. `harness/pg/adapter.py`
  must expose the same callable name and return shape, taking
  `chunk_id` instead of `qa_id`. The adapter loads from the `chunks`
  table on demand (one SELECT per call) — the recursive strategy in
  `_retrieve_recursive` only calls this for cross-ref expansion, so
  per-call latency is acceptable.

### From `harness/providers.py`

- **Env-var contract — UNCHANGED**:
  - `EMA_EMBED_MODEL` overrides the BGE model
  - `EMA_EMBED_PROVIDER` switches `huggingface` ↔ `openai`
  - Pgvector path adds `PG_DSN` and `EMA_RETRIEVER` (defaults
    documented per `decisions.md` §1 and §2)

- **LLM model default**: `_DEFAULT_LLM = "claude-haiku-4-5-20251001"`.
  Reuse via `get_llm_model()` — don't hard-code anywhere else.

- **`Settings.llm = None` for retrieve-only paths**: `configure_embed_model`
  intentionally nulls the LLM. The PG retriever doesn't need an LLM
  (it only embeds the query), so the same `Settings.llm = None`
  convention applies to the BGE-only ingest pass too.

### From `config.py`

- **dotenv pattern**: `load_dotenv(_env_file, override=False)`. New
  vars `PG_DSN` and `EMA_RETRIEVER` follow the same `os.getenv(VAR, default)`
  + `Path(...).expanduser()` (where applicable) pattern. Sample:
  ```python
  PG_DSN = os.getenv("PG_DSN", "postgresql://ema_nlp:ema_nlp@localhost:5432/ema_nlp")
  EMA_RETRIEVER = os.getenv("EMA_RETRIEVER", "faiss")  # flipped to "pgvector" by NARR-028
  ```

---

## 4. Status & TODO before code starts

- `state.json.status` is still `planning_complete`. The next code task
  (NARR-001) bumps it to `implementing` and sets
  `current_task: "NARR-001"`.
- After each task lands, `state.json` is updated: task status →
  `completed`, `current_task` advances per dependency graph.
- For 3090-PC-gated tasks (see §2), status moves to `completed` only
  after the PC run; until then they sit at `in_progress` with a
  `metadata: {gated_on: "3090 PC"}` field so the cut-point is visible.
