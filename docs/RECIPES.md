# Recipes — the config-driven retrieve→generate engine

A **recipe** is one YAML file that describes one pipeline. It configures the single engine —
a LlamaIndex `FunctionAgent` — with a system prompt, a tool list, and retrieval/generation
settings. Recipes are what the Chainlit dropdown lists, what `build_recipe` assembles, and
what gets stamped (honestly) on every MLflow trace.

The design principle: **the recipe prescribes the orchestration; the agent does not
improvise it.** RAG techniques are realized as *tools + instructions* (see
[`RAG_TECHNIQUES.md`](RAG_TECHNIQUES.md)) — the recipe lists the agent's tools, and the
prompt tells it when to use them. Adherence is checked *afterwards* (the MLflow trace shows
which tools actually ran; the optional judge layer scores the answer), not enforced by
hand-written control flow.

> **Try it live:** notebook [`docs/examples/03_routing_and_full_agent.ipynb`](examples/03_routing_and_full_agent.ipynb)
> §3 builds a recipe with `build_recipe` and runs it headless — the same path the chat UI
> uses, from plain Python.

## Where recipes live

```
harness/configs/recipes/<name>.yaml        # built-in recipes
$EMA_CONFIG_DIR/recipes/<name>.yaml        # your recipes (override built-ins of the same name)
$EMA_CONFIG_DIR/prompts/<name>.md          # your prompts (override harness/prompts/)
```

Set `EMA_CONFIG_DIR` to keep recipes and prompts **outside the source tree**. The registry
(`harness/recipes/registry.py`) discovers both locations; a recipe added to either appears
in the dropdown with no code change. `EMA_RECIPE=<name>` sets the default; otherwise the
recipe flagged `default: true` (or the first by name) is used.

## Anatomy of a recipe

There is **one engine** — a LlamaIndex `FunctionAgent`. A recipe is just its
configuration; the **toolset + system prompt define the technique** (naive RAG = the agent
with one `ema_search` tool; CRAG = the agent + `corrective_search`; ReAct = the agent with
search/resolve tools and a reason-act prompt). There is no separate "mode" or "pattern".

```yaml
recipe:
  label: "Corrective RAG (agentic)"      # dropdown label
  description: "..."                       # shown under the label
  default: false                          # exactly one recipe should be true

  orchestration:
    system_prompt: agent_crag.md          # harness/prompts/ or $EMA_CONFIG_DIR/prompts/
    tools: [corrective_search, ema_search]  # names from the tool registry (harness/tools)
    output_schema: RegulatoryAnswer       # pydantic structured output (registry.py:_OUTPUT_SCHEMAS)

  retrieval:
    index_profile: neo4j_hier             # harness/configs/index/<name>.yaml
    pipeline: none                        # none | a configs/retrieval/<name>.yaml (e.g. native)
    routing: none                         # none | a configs/routing/<name>.yaml (query→category
                                          #   prior for ema_search — see RETRIEVAL.md §7)
    fewshot:                              # optional rated-trajectory few-shot injection
      enabled: false
      k: 3
      min_rating: 4
      min_examples: 1                     # suppress injection below this many qualifying hits (≤ k)

  generation:
    model: claude_opus                    # models.yaml model name (live-overridable in the UI)
    temperature: 0.0

  judge:                                  # optional post-generation judge layer
    enabled: false
    judges: [faithfulness]                # gold-free judges run inline (correctness is eval-only)
    model_role: judge                     # models.yaml role (e.g. judge or reviewer)
    threshold: null                       # 1-5; set to enable the soft reviewer gate (F18):
    on_fail: annotate                     #   score < threshold → visible caution note (advisory,
                                          #   never blocks); verdict stamped as ema.judge.passed
```

### Opt-in stages (off by default → GPU-light)
- **`retrieval.pipeline`** — set to a `configs/retrieval/<name>.yaml` (e.g. `native`) to turn
  on query-expansion + rerank. `rerank:` accepts `cross_encoder` / `llm_sme` (GPU/LLM cost
  per turn) and the free deterministic `doc_type_priority` (source-type ordering, e.g.
  guidelines before EPARs — see [`CITATIONS.md`](CITATIONS.md) §4).
- **`retrieval.fewshot.enabled`** — inject the top-k rated past answers (👍=5/👎=1 in the
  semantic cache) as few-shot examples. Needs ≥ `min_examples` rated entries to fire.
- **`judge.enabled`** — run gold-free judges (`faithfulness`) on each answer vs its context;
  the score is shown in the chat and logged to MLflow as an LLM-judge assessment. Add
  `judge.threshold` to turn the score into a *recommendation*: a below-threshold (or
  unscorable) answer ships with a visible ⚠️ caution note — it is never blocked.
- **`retrieval.routing`** — set to a `configs/routing/<name>.yaml` table to give `ema_search`
  a per-query source-category prior (keyword rules → prefer/filter categories). Combine with
  a steered index profile (`neo4j_steered`: category quotas + LINKS_TO expansion) for the
  full steering stack — see [`RETRIEVAL.md`](RETRIEVAL.md) §7.

## Transparency (MLflow)

The *resolved* recipe is stamped on every turn's trace (`ema.recipe`, `ema.orchestration.*`,
`ema.retrieval.*`, `ema.generation.*`, `ema.fewshot.enabled`, `ema.judge.enabled`). Stamping
is **honest**: a disabled stage reads as `enabled=False` with no detail, and runtime facts
(`ema.fewshot.injected`, the judge scores) are stamped when they actually happen — the trace
never advertises a stage that did not run.

## Built-in recipes

| Recipe | Tools | Pipeline | Notes |
|---|---|---|---|
| `naive_rag` (default) | ema_search | none | lightest baseline — prompt says retrieve once |
| `crag_agentic` | corrective_search, ema_search | none | grade+rewrite-retry for T2/T3 |
| `react_agentic` | ema_search, resolve_substance | none | reason+act loop |
| `regulatory_agent` | ema_search, resolve_substance | none | the full agent |
| `agentic_reranked` | ema_search, resolve_substance | native | + query-expansion + rerank (GPU) |
| `agentic_judged` | ema_search, resolve_substance | none | + inline faithfulness judge |
| `regulatory_fewshot` | ema_search, resolve_substance | none | + rated-trajectory few-shot injection (👍-rated past answers) |
| `steered_agent` | ema_search, resolve_substance | none | + source-category steering: `routing: default` + `neo4j_steered` profile (quotas + LINKS_TO expansion); needs the category backfill — RETRIEVAL.md §7 |

## Worked examples

Three complete configurations, from simplest to fully loaded. Each is runnable as-is:
save it under `$EMA_CONFIG_DIR/recipes/<name>.yaml` (or `harness/configs/recipes/`) and it
appears in the UI dropdown; or run it directly:

```bash
python scripts/run_agent_demo.py --recipe <name> "What is the AI for NDMA?"
python scripts/run_eval.py --recipe <name> --types T1 --limit 2   # benchmark smoke run
```

### Example 1 — plain "simple RAG" (retrieve once, answer)

The classic retrieve-then-generate pipeline (Lewis et al. 2020). One tool, a prompt that
forbids extra searching, nothing else:

```yaml
# $EMA_CONFIG_DIR/recipes/my_simple_rag.yaml
recipe:
  label: "My simple RAG"
  description: "One retrieval, answer strictly from the passages."
  orchestration:
    system_prompt: agent_naive.md      # "call ema_search once, answer only from passages"
    tools: [ema_search]                # exactly one tool = no agentic behavior to speak of
    output_schema: RegulatoryAnswer
  retrieval:
    index_profile: neo4j_hier          # the live Neo4j graph (only built profile)
  generation:
    model: claude_opus                 # any name from configs/models.yaml `models:`
    temperature: 0.0
```

That is the entire configuration — the built-in `naive_rag` recipe is exactly this. The
"technique" is carried by two choices: the single `ema_search` tool and the
`agent_naive.md` prompt. Retrieval `k` comes from the index profile (default 10);
override live in the UI settings panel or per profile.

### Example 2 — reproducing the CRAG paper (Yan et al. 2024, arXiv:2401.15884)

CRAG's core idea: **don't trust retrieval blindly** — grade the retrieved passages with a
lightweight evaluator, and when they don't cover the question, take a corrective action
and retry before generating. Here the whole corrective loop is deterministic code inside
the `corrective_search` tool; the recipe just hands the agent that tool and a prompt
saying when to use it:

```yaml
# harness/configs/recipes/crag_agentic.yaml (built-in)
recipe:
  label: "Corrective RAG (agentic)"
  description: "Agent uses corrective_search (grade + rewrite-retry) for multi-hop questions."
  orchestration:
    system_prompt: agent_crag.md
    tools: [corrective_search, ema_search]   # corrective loop + plain search fallback
    output_schema: RegulatoryAnswer
  retrieval:
    index_profile: neo4j_hier
  generation:
    model: claude_opus
    temperature: 0.0
```

How the paper's components map onto this repo (and where we deliberately deviate):

| CRAG paper | Here | Where |
|---|---|---|
| Retrieval evaluator (correct / incorrect / ambiguous) | LLM grader scores each passage 0/1/2 + lists `missing_facts`; "sufficient" = a 2-scored passage **and** no gaps | `harness/retrieval/corrective.py` (`GRADE_SYSTEM`, `is_sufficient`) — the grader runs on the cheap `grader` model role, not the expensive agent model |
| Corrective action: web search | **Query rewrite + re-retrieve over the corpus** — this project is deliberately corpus-only (the benchmark's contamination story depends on it), so there is no web fallback | `REWRITE_SYSTEM` + the loop in `harness/tools/corrective_search.py` |
| Bounded retries | `max_cycles` (default 2); the loop keeps the **best-graded** retrieval across cycles, not blindly the last | `corrective_search.py` (`grade_key` best-so-far) |
| Knowledge refinement (decompose–recompose) | Not implemented (candidate future tool) | — |
| Generate once, after correction | The agent answers from the corrected passages; the tool returns *context + an honest grade note* ("STILL MISSING: …"), never an answer | `grade_note` → the agent's prompt tells it to reflect residual gaps in `caveats`/`confidence` |

To *experiment* with the technique, everything is a visible knob: the grading rubric and
rewrite prompt are plain text in `harness/retrieval/corrective.py`; the grader model is
`roles.grader` in `models.yaml`; the retry bound is the tool's `max_cycles`. The MLflow
trace shows every grade/rewrite step, so you can check adherence per question.

### Example 3 — the kitchen sink (rerank + source-type priority + judge gate + few-shot)

Every optional stage enabled at once — useful as a menu of what exists. Each stage costs
latency/GPU/LLM calls, so real recipes should enable only what a benchmark failure
justifies:

```yaml
# $EMA_CONFIG_DIR/recipes/full_stack.yaml
recipe:
  label: "Full stack (demo)"
  description: "Query expansion + rerank + source-type priority + judge gate + few-shot."
  orchestration:
    system_prompt: agent_regulatory.md
    tools: [ema_search, resolve_substance]
    output_schema: RegulatoryAnswer
  retrieval:
    index_profile: neo4j_hier
    pipeline: my_pipeline                # -> $EMA_CONFIG_DIR/retrieval/my_pipeline.yaml (below)
    fewshot:
      enabled: true                      # inject 👍-rated similar past answers…
      k: 3
      min_rating: 4                      # …rated ≥4/5 (👍 = 5.0)…
      min_examples: 1                    # …as soon as one qualifying example exists
  generation:
    model: claude_opus
    temperature: 0.0
  judge:
    enabled: true
    judges: [faithfulness]               # gold-free, runs on every turn
    model_role: judge                    # or `reviewer` — a models.yaml role
    threshold: 3                         # score <3 → visible ⚠ caution (advisory, never blocks)
    on_fail: annotate
```

```yaml
# $EMA_CONFIG_DIR/retrieval/my_pipeline.yaml — the pipeline the recipe names above
retrieval:
  query_transform: acronym               # expand "AI" → "Acceptable Intake" etc. (context-aware)
  rerank:
    - doc_type_priority                  # deterministic, free: guidelines before EPARs
    - cross_encoder                      # GPU cross-encoder rerank
  rerank_top_n: 8
  doc_type_priority: [scientific_guideline, qa, epar]   # validated category order
```

The trace for a turn run with this recipe stamps every one of those choices
(`ema.retrieval.pipeline`, `ema.retrieval.doc_type_priority`, `ema.judge.threshold`,
`ema.fewshot.*`) plus the runtime facts (`ema.fewshot.injected`, `ema.judge.passed`).

## Add your own

1. (Optional) write a prompt `.md` under `harness/prompts/` or `$EMA_CONFIG_DIR/prompts/`
   that prescribes how the agent should use its tools (see the built-in `agent_*.md`).
2. Drop a `recipe.yaml` in `harness/configs/recipes/` or `$EMA_CONFIG_DIR/recipes/`.
3. To add a *new tool*, implement + register it in `harness/tools/` (see
   [`RAG_TECHNIQUES.md`](RAG_TECHNIQUES.md) "Adding a new technique as a tool") and list it
   in the recipe's `tools`.
4. The recipe appears in the dropdown automatically. Verify what ran in the MLflow trace.

## Run it

```bash
./run_ui.sh                                   # Chainlit + MLflow :5000; pick a recipe in the panel
EMA_RECIPE=crag_agentic chainlit run app.py   # set the default recipe
python scripts/run_agent_demo.py --recipe crag_agentic "What is the AI for NDMA?"
```
