# Agentic RAG — usage guide (how-to)

> **Note:** the live UI and eval select a **recipe** (`harness/configs/recipes/*.yaml`), not a
> raw "workflow strategy" — see [`RECIPES.md`](RECIPES.md). The agent internals below (tool
> registry, structured output, judges, ontology) are unchanged; only the old workflow/prompt
> selectors are superseded by the recipe dropdown.

A practical, task-by-task guide to the **agentic layer**: a LlamaIndex `FunctionAgent` + tool
registry that returns a structured, cited `RegulatoryAnswer`, plus its MLflow
run-recording/tracing, `mlflow.genai` judges, and typed ontology enrichment. The agent is the
single engine; a **recipe** (`harness/configs/recipes/*.yaml`) configures which tools, prompt,
and schema it runs with. The live Chainlit app is MLflow-traced (autolog), like everything else.

- **Design / rationale:** [`TARGET_ARCHITECTURE.md`](TARGET_ARCHITECTURE.md)
- **Verification runbook + results (T1–T6; §8 = the pending 2026-07-07 walk):** [`RUNTIME_VERIFICATION.md`](RUNTIME_VERIFICATION.md)
- **Recipes (the config surface, with worked examples):** [`RECIPES.md`](RECIPES.md) · techniques: [`RAG_TECHNIQUES.md`](RAG_TECHNIQUES.md)
- **Citations / SME review / export:** [`CITATIONS.md`](CITATIONS.md)
- **Retrieval store:** [`RETRIEVAL.md`](RETRIEVAL.md)

Everything below was run on the GPU host (`marvin-gpu`) on 2026-06-22.

---

## 0. Prerequisites (once per machine / session)

```bash
# 1. Data services — MongoDB + Neo4j (Docker). Idempotent; health-checks.
scripts/start_services.sh

# 2. Python deps (pulls mlflow>=3, llama-index, etc.)
uv pip install -e ".[dev]"        # or: pip install -e ".[dev]"

# 3. Credentials in ~/Nextcloud/Datasets/ema_nlp/ema_nlp.env (loaded via python-dotenv):
#    ANTHROPIC_API_KEY      — LLM key
#    ANTHROPIC_BASE_URL     — optional gateway (e.g. https://gw.claudeapi.com); the agent AND
#                             the mlflow judges route through it automatically
#    NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD   — bolt://localhost:7687 on this host
#    CHAINLIT_AUTH_SECRET, UI_PASSWORD         — only for the chat UI (task 5)
```

**Sanity check the graph is intact (no LLM, no rebuild):**

```bash
python - <<'PY'
import config
from harness.indexing import load_index_profile, open_index, build_retriever
p = load_index_profile(); r = build_retriever(p, open_index(p))
print("hits:", len(r.retrieve("nitrosamine acceptable intake limit")))   # expect ~9–10
PY
```

> **GPU / model-cache notes.** The query embedder `BAAI/bge-large-en-v1.5` is already cached.
> The **first** agent run (or any rerank) downloads `BAAI/bge-reranker-large` — so **don't** set
> `HF_HUB_OFFLINE=1` on that first run (it needs network). Once both are cached, prefix commands
> with `HF_HUB_OFFLINE=1` to silence HF metadata warnings. The 3090 is power-capped to 250 W
> (GSP-crash mitigation); single agent / rerank calls are light. **Never rebuild the Neo4j index**
> unless the sanity check above returns 0 — it's a ~15 h GPU run.

---

## Task 1 — Ask the agent a question (CLI)

```bash
python scripts/run_agent_demo.py "What is the Acceptable Intake for NDMA?"
```

What happens: opens the Neo4j index → builds the retriever (BGE on GPU) → builds the
`FunctionAgent` (tools: `ema_search` + `resolve_substance`, output schema `RegulatoryAnswer`) →
runs it → prints the answer + caveats + citations → records an MLflow run (task 2).

Expected output (abridged):

```
=== ANSWER ===
The EMA Acceptable Intake (AI) for NDMA (N-nitrosodimethylamine, CAS 62-75-9) is 96.0 ng/day...
=== CITATIONS ===
 - https://www.ema.europa.eu/.../sartans-article-31-referral-chmp-assessment-report_en.pdf
 - https://pubchem.ncbi.nlm.nih.gov/compound/6124      # ← resolve_substance tool fired
```

Pass any question as the argument. The answer is a Pydantic `RegulatoryAnswer`
(`answer`, `claims[]` with claim-level `citations`, `confidence`, `caveats`).

**Programmatic** (your own script):

```python
import config
from harness.indexing import load_index_profile, open_index
from harness.recipes import build_recipe, default_recipe_name, get_recipe

recipe = get_recipe(default_recipe_name())            # or get_recipe("crag_agentic") etc.
index = open_index(load_index_profile(recipe.index_profile))
runner = build_recipe(recipe, index)                  # AgentWorkflowAdapter (invoke/ainvoke)
result = runner.invoke({"question": "Which committee sets nitrosamine limits?"})
answer = result["answer"]                             # RegulatoryAnswer
print(answer.answer, [c.source_url for c in answer.citations])
```

---

## Task 2 — Inspect runs & traces in MLflow

**Run recording** (`record=True`, also done by the demo) logs to a local file store
`./mlruns`, experiment **`ema_nlp`**: resolved-config params (`ema.retrieval.*`), answer metrics
(`answer_chars`, `num_citations`, `num_claims`, `confidence`), and the answer text artifact —
reproducibility without `log_model`.

```bash
# View the runs (mlflow 3 puts the file store in "maintenance mode", so opt out):
MLFLOW_ALLOW_FILE_STORE=true mlflow ui --backend-store-uri ./mlruns   # → http://localhost:5000
```

**Autolog (trace spans).** `setup_tracing(default_experiment())` (what the demo script does) enables
`mlflow.llama_index.autolog()` — every retrieval / tool call / LLM call becomes a span. Verified
(T3): traces **complete** (`state=OK`); the mlflow#13352 "In Progress" hang does **not** occur on
mlflow 3.14 + llama-index 0.14. View them in the **Traces** tab of the run. If autolog ever hangs
on a future version, `harness/obs/tracing.py::traced()` is the explicit-span fallback.

> The **Chainlit app** (task 5) is also traced by **MLflow** (via `mlflow.llama_index.autolog()`,
> against the `run_ui.sh` tracking server on :5000). The `record=True` run-recording shown here
> is for these CLI/eval entrypoints; the live app records traces + 👍/👎 feedback to the same MLflow.

---

## Task 3 — Ontology enrichment (semantic Layer 2)

Extract typed entities + relations (`SchemaLLMPathExtractor`) from corpus chunks into the existing
Neo4j graph. Additive (`embed_kg_nodes=False` keeps the chunk vector index intact).

```bash
# Dry-run — pure, no LLM/Neo4j; prints the plan (entities/relations/validation triples):
python -m harness.ontology.enrich --schema ema --scope nitrosamines --dry-run

# Real — LLM extraction + Neo4j writes. --limit bounds matching docs (recommended on first runs):
python -m harness.ontology.enrich --schema ema --scope nitrosamines --limit 5
```

- **Scopes:** `nitrosamines` (keyword-filtered: nitrosamine/ndma/ndea/acceptable intake) or `all`.
  A keyword scope scans the **full corpus** for matches, so always pass `--limit N` on first runs
  to keep it fast and cheap. `--scope all` enriches everything (a long run).
- **Model:** `--model-role grader` (Haiku, default) works; a stronger model (`--model-role agent`)
  gives higher recall.
- **What lands in Neo4j:** typed entity nodes — labels are **UPPER-CASE** (`:SUBSTANCE`, `:LIMIT`,
  `:GUIDELINE`, …; llama-index normalises them) — plus typed relations (`HAS_LIMIT`, `APPLIES_TO`, …),
  each carrying `triplet_source_id` provenance. `strict=True` keeps only schema-validated
  `(subject, relation, object)` triples (high precision, lower recall — the owner's design).
- **Schema** lives in `harness/configs/ontology/ema.yaml` (entities + relations, Title-Case source
  of truth).

**Inspect what was written:**

```python
import config
from harness.indexing.property_graph import neo4j_store_from_env
store = neo4j_store_from_env()
LABELS = ["SUBSTANCE","LIMIT","GUIDELINE","PRODUCT","PROCEDURE","COMMITTEE","REQUIREMENT"]
print(store.structured_query(
    "MATCH (e) WHERE any(l IN labels(e) WHERE l IN $labels) "
    "RETURN [l IN labels(e) WHERE l IN $labels][0] AS type, e.name AS name LIMIT 15", {"labels": LABELS}))
```

**Undo a test run** (surgical, by provenance — never a broad label delete):

```python
store.structured_query("MATCH (e) WHERE e.triplet_source_id IN $ids DETACH DELETE e", {"ids": ["<doc_id>"]})
```

---

## Task 4 — Judges & offline evaluation

Build `mlflow.genai` LLM judges (faithfulness + correctness) from the prompts in
`harness/judges/*.md` and score a dataset with `mlflow.genai.evaluate`.

**Quick mechanism check** (fast — fixed answer, no live agent; this is the path verified in T5):

```python
import config
from harness.eval import ema_judges, build_predict_fn, run_evaluation
from harness.schemas import RegulatoryAnswer

judges = ema_judges(model="anthropic:/claude-opus-4-7")   # judge model ≠ generator (avoid self-bias)

# score a single judge directly:
corr = next(j for j in judges if "correct" in j.name.lower())
fb = corr(inputs={"question": "What is the AI for NDMA?"},
          outputs="The acceptable intake for NDMA is 96.0 ng/day.",
          expectations={"gold_answer": "96 ng/day"})
print(fb.value, fb.rationale)            # -> 5  "...correctly identifies the AI as 96 ng/day"

# run a tiny evaluation with a fixed predict_fn:
data = [{"inputs": {"question": "What is the AI for NDMA?"}, "expectations": {"gold_answer": "96 ng/day"}}]
predict_fn = build_predict_fn(lambda q: RegulatoryAnswer(answer="The AI for NDMA is 96.0 ng/day."))
result = run_evaluation(data, predict_fn=predict_fn, scorers=judges, experiment="ema_eval")
```

**Full evaluation over the live agent** — same call, but the predict_fn runs the agent for each
row (so it's slower: it loads the index + reranker and `evaluate` also does a validation pre-run):

```python
from harness.indexing import load_index_profile, open_index
from harness.recipes import build_recipe, get_recipe

recipe = get_recipe("naive_rag")                       # the recipe under evaluation
index = open_index(load_index_profile(recipe.index_profile))
runner = build_recipe(recipe, index)
predict_fn = build_predict_fn(runner)   # question -> {answer, citations, ..., context_passages}
result = run_evaluation(data, predict_fn=predict_fn, scorers=judges, experiment="ema_eval")
```

- Judges route through `ANTHROPIC_BASE_URL` automatically (the gateway's `/v1/messages` endpoint).
- Per-sample scores appear in the **Traces** tab of the eval run in the MLflow UI.
- **Judge alignment** (`harness.eval.align_judge(judge, traces)`) — the `.align(...)` API is present
  but alignment needs ≥10 (50–100 better) traces with paired human + judge assessments, so it's
  deferred. The DSPy bootstrap loop (`harness/eval/bootstrap.py`) is likewise scaffolded, not run.

---

## Task 5 — Use the agent in the Chainlit chat UI

```bash
bash run_ui.sh                 # MLflow server + Chainlit; open the printed localhost URL, log in
```

Select the recipe in either place:

- **At session start:** pick a chat profile (one per recipe), or
- **Live, any time:** open the right-hand settings panel and pick from the **Recipe** dropdown
  (the panel is the live source of truth; switching rebuilds the pipeline in place).

The agent runs **MLflow-traced** (the "View traces →" link points at the MLflow UI experiment's
Traces tab on :5000), shows its citations in the source sidebar, and supports 👍/👎 feedback
(written as MLflow trace assessments). In-app the agent uses a
plain retrieve (GPU-light); the full query-expansion + rerank pipeline is on the CLI demo / eval
paths (task 1/4).

---

## Task 6 — Re-verify after changes

Re-run the offline suite and the T1–T6 steps when you touch the agentic layer:

```bash
# offline (fast, ~77+ tests):
HF_HUB_OFFLINE=1 python -m pytest tests/test_schemas.py tests/test_tools.py tests/test_obs_runs.py \
  tests/test_agents.py tests/test_agent_session.py tests/test_retrieval_pipeline.py \
  tests/test_eval_predict.py tests/test_eval_bootstrap.py tests/test_eval_judges.py \
  tests/test_ontology_enrich.py tests/test_agent_workflow_adapter.py -q

ruff check . && mypy harness/agents harness/eval harness/ontology   # lint + types (agentic layer)
```

Then walk [`RUNTIME_VERIFICATION.md`](RUNTIME_VERIFICATION.md) T1→T6 for the live paths.

---

## Configuration reference

| Concern | File | Key knobs |
|---|---|---|
| Recipe (agent + retrieval + generation) | `harness/configs/recipes/*.yaml` | `system_prompt`, `tools`, `output_schema`, `index_profile`, `pipeline`, `model`, `fewshot`, `judge` |
| Retrieval pipeline | `harness/configs/retrieval/native.yaml` | `query_transform` (none/acronym/llm_rewrite), `rerank` (cross_encoder/llm_sme), `rerank_top_n` — retrieval `k` lives in the index profile |
| Models & roles | `harness/configs/models.yaml` | `models:` defs + `roles:` (agent/grader/judge/reranker/…) |
| Ontology schema | `harness/configs/ontology/ema.yaml` | `entities`, `relations` |
| Index profile | `harness/configs/index/neo4j_hier.yaml` | `embed_model`, `chunking`, `scope` (ingest cap), `retrieval` |

Add a tool: register it in `harness/tools/` and list it under `agent.tools` — no code change.
Swap a model for a role: edit `roles:` in `models.yaml`. Both are read at build time.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `MlflowException: filesystem tracking backend ... maintenance mode` | mlflow 3 gated the file store. `setup_mlflow` sets `MLFLOW_ALLOW_FILE_STORE=true` automatically; for the `mlflow ui` CLI export it yourself, or use `--backend-store-uri sqlite:///mlflow.db`. |
| First agent run hangs on HF download | It's pulling `bge-reranker-large`. Don't set `HF_HUB_OFFLINE=1` until both BGE models are cached. |
| Judge error `invalid x-api-key` / `Not found` | The mlflow judge gateway adapter needs the **full** `…/v1/messages` endpoint — handled by `_anthropic_judge_base_url` from `ANTHROPIC_BASE_URL`. A bare host (→404) or `api.anthropic.com` with a gateway key (→invalid key) means the var is unset/partial. |
| `--scope nitrosamines` enriches 0 docs | (Fixed 2026-06-22.) Keyword scopes now scan past the profile's ingest `scope.limit`; pass `--limit N` to bound the (full-corpus) scan. |
| Ontology extraction returns 0 entities | `strict=True` drops triples that don't match the validated schema; entity *types* must be the upper-cased forms (handled by `build_schema_extractor`). For broader recall, relax to `strict=False` in code. |
| GPU wedged under load | 250 W power cap is the mitigation; throttle batches. See the project memory on GSP crashes. Single agent calls are safe. |
