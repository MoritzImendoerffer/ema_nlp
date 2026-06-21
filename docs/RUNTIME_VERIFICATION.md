# Runtime verification runbook — agentic layer (GPU host)

> **For a fresh Claude Code session on the GPU host (`marvin-gpu`) with no prior chat
> context.** Read this top-to-bottom before doing anything. It tells you what was built,
> where to catch up, the guardrails, and the exact task order to verify it on real infra.

## 1. Catch up (read these first, in order)

1. **`CLAUDE.md`** — project guardrails + the "Agentic layer in progress" banner.
2. **`docs/TARGET_ARCHITECTURE.md`** — the full design, the status banner, **§7 build order**,
   and **§8 spikes / things to verify at runtime**.
3. **`.claude/HISTORY.md`** — the **last ~10 rows** are exactly what was built, in order:
   foundation (schemas/tools/agents/obs/ontology) → retrieval pipeline → integration glue →
   MLflow run-recording → phase-2 scaffolding (tracing/native-PG/ontology/session) → eval
   (judges/bootstrap) → docs refresh.
4. **PR #46** (`gh pr view 46` or GitHub) — the "Known things to verify at runtime" list.

## 2. State of play

- Branch: **`claude/agentic-rag-foundation`** (this is where all the work is; `main` has none of it).
- An **additive** agentic layer lives under `harness/{schemas,tools,agents,retrieval,obs,ontology,eval}/`.
  Foundation is **unit-tested offline (77 tests)** but **NOT runtime-verified** and **NOT wired
  into `app.py`**. The live app is still the LlamaIndex **workflow** stack + **Arize Phoenix**.
- **Your job this session:** run the runtime-gated paths on real infra (Neo4j + LLM + MLflow),
  fix what breaks, on the branch — without disturbing the live workflow/Phoenix path.

## 3. Guardrails (do not violate)

- Develop on **`claude/agentic-rag-foundation`**; commit + push there; **append a `.claude/HISTORY.md`
  row** after any code/config change (per `CLAUDE.md`).
- **Additive only.** Do **not** modify the live workflow stack or `app.py`'s Phoenix wiring unless
  explicitly asked. The MLflow switch is a *target*, not a completed migration.
- **Do not rebuild the Neo4j index** unless the smoke test in §4 returns 0/errors — the 5.82M-embedding
  build is a ~15 h GPU run. The graph already exists in the `ema_neo4j_data` Docker volume.
- Keep diffs scoped to the agentic layer; prefer minimal fixes; re-run the relevant test after each fix.

## 4. Startup

```bash
git fetch origin && git checkout claude/agentic-rag-foundation && git pull
pip install -e ".[dev]"                 # includes mlflow>=3.0
pip install "mlflow[llama-index]"       # only for autolog tracing of the agent
# optional: pip install dspy            # only for the bootstrap loop (lazy import)
scripts/start_services.sh               # Mongo (mongo:8.0.4) + Neo4j
```
Env file `~/.myenvs/ema_nlp.env` must have `ANTHROPIC_API_KEY`, `CHAINLIT_AUTH_SECRET`,
`NEO4J_PASSWORD` (see `docs/SETUP.md`).

**Verify the graph is intact (no rebuild, no LLM):**
```bash
python - <<'PY'
from harness.indexing import load_index_profile, open_index, build_retriever
p = load_index_profile(); r = build_retriever(p, open_index(p))
print("hits:", len(r.retrieve("nitrosamine acceptable intake limit")))
PY
```
Expect ~10 hits. If 0/errors → the volume was wiped; only then rebuild with
`harness.indexing.build_index(p, reset=True)`.

## 5. Verification tasks (do in order; fix-on-fail, then commit + HISTORY row)

**T1 — offline tests pass on this machine.**
```bash
pytest tests/test_schemas.py tests/test_tools.py tests/test_obs_runs.py tests/test_agents.py \
       tests/test_agent_session.py tests/test_retrieval_pipeline.py tests/test_eval_predict.py \
       tests/test_eval_bootstrap.py
```
(~77 pass. `mypy .` may show ~10 errors in `harness/indexing/*` from llama-index version skew —
not from the new code; ignore unless you're pinning versions.)

**T2 — agent end-to-end (the main event).**
```bash
python scripts/run_agent_demo.py "What is the Acceptable Intake for NDMA?"
```
Expect a `RegulatoryAnswer` (answer + citations) printed, and an MLflow run in `./mlruns`.
First run downloads `bge-large` reranker onto the GPU. **Likely break points + fixes:**
- `FunctionAgent.run` arg name → `python -c "import inspect; from llama_index.core.agent.workflow import FunctionAgent; print(inspect.signature(FunctionAgent.run))"`; `harness/agents/runner.py` uses `user_msg=` — adjust if needed.
- structured output → confirm `AgentOutput.structured_response` is populated by `output_cls`; `coerce_answer` falls back to response text + citations otherwise.
- reranker → `harness/configs/retrieval/native.yaml` sets `rerank: [cross_encoder]`; set it to `[]` to isolate problems, then re-enable.

**T3 — MLflow autolog tracing of the agent.**
Enable in `harness/obs/tracing.py` via `setup_tracing(...)`; run T2 again; confirm the trace
**completes** (watch for the mlflow#13352 "In Progress" hang on Workflow-based agents). If it hangs,
fall back to the explicit `traced()` span (already in `tracing.py`) and note it.

**T4 — ontology enrichment (Layer 2).**
```bash
python -m harness.ontology.enrich --schema ema --scope nitrosamines --dry-run   # inspect the plan
python -m harness.ontology.enrich --schema ema --scope nitrosamines             # real (LLM + Neo4j)
```
Check the `SchemaLLMPathExtractor` `kg_validation_schema` shape for your llama-index version
(`harness/ontology/enrich.py::schema_extractor_kwargs`); adjust if extraction errors.

**T5 — (optional) judges + eval.** Build a judge (`harness/eval/judges.py::ema_judges`), run
`mlflow.genai.evaluate` over a tiny dataset via `harness/eval/`. Verify the `judge.align(...)` API
shape for the installed mlflow (`align_judge`).

**T6 — (only if asked) wire the agent into `app.py`** as a selectable mode alongside the workflows.

## 6. View results

```bash
mlflow ui        # ./mlruns → http://localhost:5000  (agent runs: resolved-config params + answer metrics)
bash run_ui.sh   # the live Chainlit workflow app (Phoenix-traced) — the untouched baseline
```

## 7. After each task

Green → append a `.claude/HISTORY.md` row, `git commit`, `git push origin claude/agentic-rag-foundation`.
Red → capture the traceback, make the **minimal** fix on the branch, re-run that task, then commit.
Report progress against the T1–T6 list.
