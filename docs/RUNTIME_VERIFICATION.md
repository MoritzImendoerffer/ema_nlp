# Runtime verification runbook — agentic layer (GPU host)

> **For a fresh Claude Code session on the GPU host (`marvin-gpu`) with no prior chat
> context.** Read this top-to-bottom before doing anything. It tells you what was built,
> where to catch up, the guardrails, and the exact task order to verify it on real infra.

> ✅ **Completed 2026-06-22 — all of T1–T6 green** (commits `22be5e7`→`1789101` on this branch;
> details per task in `.claude/HISTORY.md`). Summary:
> - **T1** — 77 offline tests pass (fixed one CI-only assumption in `test_obs_tracing`).
> - **T2** — agent end-to-end works (correct `RegulatoryAnswer`, both tools fire); fixed
>   `AgentSession.arun(record=True)` to configure the MLflow backend (mlflow 3 file-store crash/misroute).
> - **T3** — MLflow autolog traces **complete** (`state=OK`); mlflow#13352 did **not** occur.
> - **T4** — ontology enrichment writes typed entities into Neo4j; fixed 3 defects (Literal-type
>   construction, `strict=True` case mismatch dropping all triples, scope-limit capping keyword scopes).
> - **T5** — `mlflow.genai` judges + `evaluate` run; fixed prompt-variable mapping (shared `.md` files)
>   + gateway routing (`…/v1/messages`).
> - **T6** — agent wired into `app.py` as the selectable **"Agentic RAG"** mode (additive; registry-driven).
>
> The task steps below remain as a **re-run reference**. For day-to-day *usage* (not verification),
> see the how-to: **[`AGENTIC_GUIDE.md`](AGENTIC_GUIDE.md)**.

> ℹ️ **Update — the Phoenix→MLflow migration has since been completed.** The live Chainlit app
> (`app.py`) is now traced by **MLflow** (`mlflow.llama_index.autolog()` + `harness.obs.tracing.traced`),
> 👍/👎 feedback is written as MLflow trace assessments, and `run_ui.sh` starts an MLflow tracking
> server on **:5000** (sqlite backend `mlflow.db`) instead of Phoenix on :6006. Arize Phoenix is fully
> removed from the live path and the deps. The "do not touch Phoenix" guardrail in §3 and the
> "Phoenix still traces every turn" notes below are therefore **obsolete** — they describe the
> pre-migration state and are kept here only as history.

## 1. Catch up (read these first, in order)

1. **`CLAUDE.md`** — project guardrails + the "Agentic layer — runtime-verified" banner.
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
  Foundation is **unit-tested offline (77 tests)** and, as of 2026-06-22, **runtime-verified +
  wired into `app.py`** as the selectable "Agentic RAG" strategy (see the ✅ block above). The
  live app runs the LlamaIndex **workflow** stack (the agent is one more selectable strategy),
  now traced by **MLflow** (the Phoenix→MLflow migration has since completed — see the note above;
  at the time these tasks were run, the live app was still on Phoenix).
- **Original job (now done):** run the runtime-gated paths on real infra (Neo4j + LLM + MLflow),
  fix what breaks, on the branch. Re-run the steps below to re-verify after changes.

## 3. Guardrails (do not violate)

- Develop on **`claude/agentic-rag-foundation`**; commit + push there; **append a `.claude/HISTORY.md`
  row** after any code/config change (per `CLAUDE.md`).
- **Additive only.** Keep diffs scoped to the agentic layer; do **not** modify the live workflow
  stack unless explicitly asked. *(Historical: this bullet originally said "do not modify `app.py`'s
  Phoenix wiring" because the MLflow switch was a target — that migration is now done, so the
  guardrail no longer applies.)*
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
*(Since superseded: the workflow engine was retired 2026-06-25 and the agent is now the single
engine, selected via the recipe dropdown — see [`RECIPES.md`](RECIPES.md).)*

## 6. View results

```bash
mlflow ui        # CLI run-recording (./mlruns) → http://localhost:5000  (agent runs: resolved-config params + answer metrics)
bash run_ui.sh   # the live Chainlit app — starts the MLflow tracking server on :5000 + Chainlit on :8000
```

> `run_ui.sh` runs its own `mlflow server` (sqlite backend `mlflow.db`) on :5000 for the live app's
> traces + 👍/👎 feedback; the standalone `mlflow ui` above is just for browsing the CLI `./mlruns` runs.

## 7. After each task

Green → append a `.claude/HISTORY.md` row, `git commit`, `git push origin claude/agentic-rag-foundation`.
Red → capture the traceback, make the **minimal** fix on the branch, re-run that task, then commit.
Report progress against the T1–T6 list.

---

## 8. The 2026-07-07 walk — verify the July refactors live (NEXT STEP)

Everything since 2026-07-04 was verified offline (492 tests) + by headless boot, but not
against the live graph/LLM/browser. Run this on the GPU host (`marvin-gpu` — it has the
79,882-doc Neo4j graph, the local BGE embedder, and MongoDB), in order; fix-on-fail,
commit + HISTORY row per step, exactly like §5–§7.

```bash
scripts/start_services.sh                       # Mongo + Neo4j up + healthy
pytest -q --ignore=tests/test_mongo_source.py   # baseline: ~492 passed / 2 skipped
```

**W1 — retriever provenance (the enriched `_QUERY`).** The Cypher now projects
`title/topic_path/committee/reference_number/source_type` off the Document node:

```bash
python - <<'PY'
from harness.indexing import load_index_profile, open_index, build_retriever
p = load_index_profile(); r = build_retriever(p, open_index(p))
n = r.retrieve("nitrosamine acceptable intake limit")[0]
print({k: n.node.metadata.get(k) for k in
       ("title", "category", "committee", "chunk_id", "source_url")})
PY
```
Expect a real title, a sensible `category` (qa/scientific_guideline/…), a non-empty
`chunk_id`. If Document nodes lack a property (older build), values are `""` — acceptable,
note it.

**W2 — eval runner smoke (first live run of the R6 vehicle).**
```bash
python scripts/run_eval.py --recipe naive_rag --types T1 --limit 2
```
Expect one MLflow run (experiment per `EMA_MLFLOW_EXPERIMENT`) tagged
`ema.recipe/ema.benchmark/ema.question_type`, with faithfulness+correctness scores. Watch
for: judge gateway routing (`ANTHROPIC_BASE_URL` → `/v1/messages`), and that per-row
traces carry `context_passages`.

**W3 — the citations UI walk.** `bash run_ui.sh`, ask (recipe `naive_rag`):
*"What is the Acceptable Intake for NDMA?"* Then check, in order:
1. the answer contains clickable **`[n]` markers** and a **Sources:** line; clicking a
   marker opens the numbered source card (title, category badge, committee, score);
2. **🔍 Review citations (n)** expands to the side-by-side view; clicking an answer span
   highlights its reference card and vice versa; the retrieved quote is highlighted inside
   the full passage;
3. rate one citation (✓/~/✗ + a "prefer scientific_guideline" flag + note) → in the MLflow
   UI, the turn's trace shows a `citation_<rank>_<chunk8>` assessment with that metadata
   (Assessments panel on the trace);
4. **⬇ Export** → download both files; the HTML opens offline with working two-way
   span↔reference highlighting; the Markdown has the config table + bolded quotes;
5. **resume**: restart the browser session, reopen the thread from history → sources and
   the review panel are still there, saved verdicts visible; the export files still
   download.
   *(If claims come back unanchored — no markers — the answer still renders plainly;
   check the trace: are `claims[].text` verbatim? If the model paraphrases despite the
   prompt, consider tightening `agent_naive.md` further. Degradation is by design, not a
   crash.)*
6. give the turn a 👍 → `user_rating` assessment on the same trace; ask a *similar*
   question with recipe `regulatory_fewshot` → few-shot injection fires
   (`ema.fewshot.injected=true` on the new trace).

**W4 — `doc_type_priority` live.** Create `$EMA_CONFIG_DIR/retrieval/prio.yaml`
(`rerank: [doc_type_priority]`, `doc_type_priority: [scientific_guideline, qa, epar]`) +
a recipe pointing at it; ask a question that retrieves EPARs; confirm guideline/Q&A
sources outrank EPARs in the cards and the trace stamps
`ema.retrieval.doc_type_priority`.

**W5 — embed-model provenance.** Confirm `harness/index/query_cache.json` now has the
`{"embed_model": ..., "entries": [...]}` shape after a turn; no `.bak-*` files appeared
(no accidental model switch).

Done = all five green, committed, pushed (from a credentialed machine). After this walk,
the natural next build steps are the **closed-book baseline + lift metric** (the missing
benchmark headline — see [`ONBOARDING.md`](ONBOARDING.md) §9), then Phase 2.5's
contamination screen.

### Results — 2026-07-07/08 (GPU host) — **WALK COMPLETE ✅** (incl. browser click-through, owner-confirmed 2026-07-08: markers, review panel + verdict→assessment, export downloads, resume persistence all work in the live UI)

| Step | Result |
|---|---|
| Baseline | ✅ services healthy; full suite green |
| **W1** | ✅ live retriever returns `title`/`source_type`/real `chunk_id`/derived `category` (committee/reference_number empty where the source document has none — expected) |
| **W2** | ✅ after the two fixes below: run tagged `ema.recipe`/`ema.benchmark`/`ema.question_type`, per-row judge assessments on linked traces, and aggregated run metrics — smoke result `T1: correctness_mean=4.000, faithfulness_mean=5.000` |
| **W3** | ✅ programmatic: live turn produced verbatim-claim spans + inline `[1][2]` markers, references with full passages + located quotes, complete tagged trace; `log_citation_feedback` → `citation_1_*` assessment (verdict/rank/prefer metadata) readable on the trace; MD+HTML exports rendered with highlight machinery. **Browser click-through (markers, review panel, export download, resume) = the remaining manual step** |
| **W4** | ✅ retrieval side live: `doc_type_priority` reorders (epar > other), stable within category; stamping path exercised via the same resolved-attributes flow as `ema.recipe` |
| **W5** | ✅ live sidecar adopted the provenance format: `{"embed_model": "BAAI/bge-large-en-v1.5", entries: 27}` (26 legacy preserved + 1 new), no `.bak-*` triggered |

**Three defects found + fixed during the walk** (this is what the walk is for):

1. **Infrastructure:** the original `ANTHROPIC_BASE_URL` gateway (`gw.claudeapi.com`)
   stripped client-supplied `tools` and injected its own (probes came back calling
   `WebSearch`/`ToolSearch`) — the agent ran tool-less. Resolved by the owner switching to
   the direct Anthropic endpoint. Symptom to remember: an agent answering *"I don't have
   access to the `ema_search` tool"* means tool definitions aren't reaching the model.
2. **llama-index 0.14.22 structured output:** `generate_structured_response` forwards
   `tool_choice=None`, overriding the Anthropic wrapper's correct object → HTTP 400
   "tool_choice: Input should be an object". Fixed in `harness/llms.py::_Anthropic`
   (drops the explicit None; exact-signature override so `tool_required` support is
   still detected).
3. **anthropic-SDK × pydantic 2.13 serialization:** `AnthropicChatResponse.raw` holds
   lazily-built SDK models (`MockValSer`), so MLflow autolog's span-close `model_dump()`
   raised and `mlflow.genai.evaluate` lost the row's trace (`eval_item.trace is None`).
   Fixed by sanitizing `raw` to plain data in the same wrapper. Plus:
   `run_recipe_benchmark` now aggregates per-judge means from trace assessments onto the
   run (this mlflow version returns no aggregate metrics).

**Known cosmetic leftover:** one `Failed to end span … MockValSer` warning per agent run
remains (mlflow's own stream-accumulator span, built from pre-sanitation deltas). Traces
complete and the eval passes; chase only if it starts mattering.
