# Recipes — the config-driven retrieve→generate engine

A **recipe** is the single, config-file description of one pipeline. Every "workflow" in
the app is now one agent-centric recipe: a LlamaIndex `FunctionAgent` configured by YAML +
an instruction-led prompt. Recipes are what the Chainlit dropdown lists, what `build_recipe`
assembles, and what gets stamped (honestly) on every MLflow trace.

Design principle: **orchestration is prescribed by the recipe (prompt + config); the agent
does not improvise it.** RAG techniques are realized as *tools + instructions* (see
[`RAG_TECHNIQUES.md`](RAG_TECHNIQUES.md)); the recipe says which tools the agent has and how
the prompt tells it to use them. Adherence is verified *retrospectively* (the MLflow trace
shows which tools ran; the optional judge layer scores the answer) rather than enforced by
hand-rolled control flow.

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
  on query-expansion + cross-encoder rerank. Costs GPU per turn.
- **`retrieval.fewshot.enabled`** — inject the top-k rated past answers (👍=5/👎=1 in the
  semantic cache) as few-shot examples. Needs ≥ `min_examples` rated entries to fire.
- **`judge.enabled`** — run gold-free judges (`faithfulness`) on each answer vs its context;
  the score is shown in the chat and logged to MLflow as an LLM-judge assessment. Add
  `judge.threshold` to turn the score into a *recommendation*: a below-threshold (or
  unscorable) answer ships with a visible ⚠️ caution note — it is never blocked.

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
