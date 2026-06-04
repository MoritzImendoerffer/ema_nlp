# Harness refactors — three changes to make config exploration and tracing first-class

This document specifies three changes to `harness/` that, together, make it possible to:

1. Filter and group Phoenix traces by configuration (strategy, retrieval mode, reranker, prompt variant, LLM)
2. Compose any orchestration strategy with any retrieval ablation without code changes
3. Add a new prompt variant by editing YAML, not the workflow registry

Each change is independently shippable. Order matters: **Change 1** is highest ROI and unblocks meaningful trace analysis. **Change 2** removes a real compositional limitation. **Change 3** is cleanup but removes redundancy that would otherwise grow.

No backward compatibility is required — old YAML config names and registry keys can be hard-renamed.

> ✅ **Status (2026-06-04).** All three changes were implemented (commit `616d338`,
> TRACE-001–012). **Change 1** (Phoenix span stamping via `config_attributes()`) and
> **Change 3** (`prompt_strategy` as a YAML field; the registry is collapsed to 7 entries)
> are **shipped and in effect** — see `harness/workflows/`. **Change 2** (`build_retrieve_fn`
> composing retrieval ablations) was **superseded and removed** by the LlamaIndex-first
> retrieval refactor (LIR-012, commit `7bcf5a5`): workflows now consume a LlamaIndex retriever
> from `harness.indexing` directly, and the ablation machinery (`harness/retrieve.py`,
> `run_eval.py`) is gone. The Change 2 section below is kept only as a history note.
> See [`docs/RETRIEVAL.md`](docs/RETRIEVAL.md).

---

## Change 1 — Stamp configuration onto Phoenix span attributes

> ✅ **Shipped** (commit `616d338`). In effect: `WorkflowRunner` stamps the OpenInference /
> `ema.*` attributes returned by each workflow's `config_attributes()`. See `harness/workflows/utils.py`
> and the per-workflow `config_attributes()` methods. The original spec is retained below for context.

### Problem

`run_id` in `app.py` is a per-interaction UUID used only to locate a span for thumbs-up/down feedback. The actual configuration that produced a trace (orchestration strategy, retrieval mode, k, prompt variant, LLM model, reranker on/off, etc.) is **not** attached to any span. This means questions like:

- "Show me all CRAG runs with hybrid retrieval and reranker=sme that scored below 0.6"
- "Compare faithfulness scores grouped by prompt_strategy across all simple_rag runs"
- "Did few-shot help more on T3 multi-hop or T1 lookup?"

cannot be answered from Phoenix without cross-referencing external metadata. For a project whose central premise is comparing agentic configurations, this is a blocker.

### Approach

Modify `WorkflowRunner.ainvoke` in `harness/workflows/utils.py` to stamp OpenInference attributes onto the current root span before delegating to the underlying workflow.

Each workflow class exposes its configuration via a `config_attributes()` method returning a `dict[str, str | int | float | bool]`. `WorkflowRunner` reads this method and stamps the attributes. Since every workflow goes through the runner, one place owns the stamping logic.

### Files to touch

- `harness/workflows/utils.py` — modify `WorkflowRunner.ainvoke` to read `config_attributes()` from the wrapped workflow and stamp them on the current span
- Each workflow class in `harness/workflows/*.py` — add a `config_attributes()` method returning a `dict[str, str | int | float | bool]`
- `app.py` — pass `run_id` and `benchmark_id` (if applicable) through as workflow inputs (e.g. via a thin wrapper around `ainvoke`) so they reach the span as attributes too

### Required attributes to stamp

At minimum, the root span of every workflow run must carry:

- `ema.orchestration.strategy` — registry key (e.g. `crag`, `react`, `simple_rag`)
- `ema.orchestration.prompt_strategy` — `zero_shot` | `few_shot` | `cot_self` (where applicable)
- `ema.retrieval.strategy` — `flat` | `recursive` | `hierarchical` | `agentic`
- `ema.retrieval.mode` — `dense` | `bm25` | `hybrid`
- `ema.retrieval.k` — int
- `ema.retrieval.reranker` — `none` | `sme` | `generic`
- `ema.retrieval.query_expansion` — bool
- `ema.retrieval.topic_filter` — `none` | `keyword` | `concept`
- `ema.llm.agent_model` — model name from `models.yaml`
- `ema.llm.reranker_model` — model name where applicable, else absent
- `ema.run.id` — the `run_id` (UUID per interaction, or YAML `run_id` for eval runs)
- `ema.run.source` — `chainlit` | `eval` | `notebook` | `cli`

Use the `openinference.semconv` constants where they exist; use the `ema.*` namespace for project-specific keys.

### Implementation notes

- `WorkflowRunner.ainvoke` must stamp before calling the underlying workflow, so attributes are visible on partial / failed runs too. `invoke` (sync) delegates to `ainvoke` already, so no change needed there.
- If the OpenTelemetry current span is non-recording (Phoenix disabled), stamping must be a silent no-op — never raise.
- `config_attributes()` on workflows like CRAG should include the workflow-specific knobs (e.g. `ema.crag.max_cycles`).
- Where a workflow composes another (e.g. `crag_review`, `react_review`), the outer workflow's `config_attributes()` should include the inner's keys with appropriate prefixes — or stamp from the outermost layer only and let inner child spans carry their own structural information.
- If `config_attributes()` is missing on a workflow (e.g. during the migration), `WorkflowRunner` should degrade gracefully — log a warning once, stamp nothing, continue.

### ~~Acceptance~~ (shipped)

- ~~After running any benchmark eval, opening the Phoenix UI and filtering on `ema.orchestration.strategy == "crag" AND ema.retrieval.reranker == "sme"` returns exactly the expected runs.~~
- ~~Existing thumbs-up/down feedback flow in `app.py` continues to work unchanged.~~
- ~~A `pytest` test exists that mocks Phoenix and asserts the expected attribute keys are set on the root span for at least one workflow.~~
- ~~`PHOENIX_DISABLED=1` does not cause any test to fail.~~

### ~~Estimated effort~~ — done

---

## Change 2 — Push retrieval-layer ablations into a shared factory

> ⛔ **[SUPERSEDED]** — history note only.
>
> This change introduced a `build_retrieve_fn(ret_config, abl_config, ...)` factory in
> `harness/retrieve.py` (plus an `AblationConfig` dataclass) so that query expansion / topic
> filter / reranker ablations composed with every workflow, shared between `app.py` and
> `run_eval.py`. It was implemented in commit `616d338` (2026-05-25) and then **removed** by the
> LlamaIndex-first retrieval refactor (LIR-012, commit `7bcf5a5`, 2026-06-03): `harness/retrieve.py`,
> `run_eval.py`, and the whole pgvector/FAISS-over-corpus ablation stack are deleted. Retrieval is now
> a single LlamaIndex `HierarchicalPGRetriever` over the Neo4j `PropertyGraphIndex`, injected into
> workflows via `get_workflow(retriever=...)`. The retrieval-track ablations are spec-only and will be
> rebuilt on the Neo4j API. See [`docs/RETRIEVAL.md`](docs/RETRIEVAL.md) and `docs/RETRIEVAL_TRACKS.md`.

---

## Change 3 — Collapse `simple_rag_*` and `crag_*` into base entries with `prompt_strategy` as a YAML field

> ✅ **Shipped** (commit `616d338`). In effect: `WORKFLOW_REGISTRY` is collapsed to the 7 entries
> below (`simple_rag`, `crag`, `react`, `summarize_rag`, `crag_summarize`, `crag_review`,
> `react_review`); `prompt_strategy` (`zero_shot` / `few_shot` / `cot_self`) is a YAML field passed
> through `get_workflow(..., prompt_strategy=...)`. See `harness/workflows/registry.py`. The original
> spec is retained below for context.

### Problem

`WORKFLOW_REGISTRY` has nine entries today, but several are the same workflow with a different prompt:

- `simple_rag_zero`, `simple_rag_few`, `simple_rag_cot` — one workflow, three prompts
- `crag` plus `crag_summarize`, `crag_review` — one CRAG with a hardcoded `zero_shot` prompt strategy

Adding a fourth prompt variant (say, a self-consistency prompt) means adding three new registry entries and three new builder functions, plus equivalent expansion for any future strategy that supports prompt variants. This doesn't scale, and it pretends "strategy" and "prompt" are coupled when they aren't.

### Approach

- Reduce `WORKFLOW_REGISTRY` to one entry per orchestration *shape*: `simple_rag`, `crag`, `react`, `summarize_rag`, `crag_summarize`, `crag_review`, `react_review`.
- Move `prompt_strategy` to the YAML `orchestration:` section, e.g.:
  ```yaml
  orchestration:
    strategy: simple_rag
    prompt_strategy: cot_self
  ```
- `run_eval.py` and `app.py` read `prompt_strategy` from the YAML and pass it into `get_workflow(name, ..., prompt_strategy=...)`.
- `get_workflow` forwards it through `**kwargs` to the builder, which forwards it to the workflow's `__init__`.

No backward compatibility — old registry names (`simple_rag_zero` etc.) are removed, not aliased.

### Files to touch

- `harness/workflows/registry.py` — remove the six redundant builder functions and registry entries; keep `simple_rag`, `crag`, `react`, `summarize_rag`, `crag_summarize`, `crag_review`, `react_review`
- `harness/workflows/simple_rag.py` — `strategy` parameter remains, but is now driven by YAML
- `harness/workflows/crag.py` — add `prompt_strategy` parameter (already partly there as `strategy`, currently defaulting to `"zero_shot"`)
- `harness/workflows/composites.py` — propagate `prompt_strategy` through `crag_summarize`, `crag_review`, `react_review`
- `harness/run_eval.py` — read `orchestration.prompt_strategy` and pass to `get_workflow()`
- `app.py` — same
- All YAML configs in `harness/configs/` that reference removed registry keys — rewrite to use the new schema
- Update `WORKFLOW_REGISTRY` docstring to reflect the new shape

### Naming consistency

Settle on **one** keyword. The codebase currently mixes `strategy` (the prompt variant inside `SimpleRAGWorkflow.__init__`) with `strategy` (the orchestration registry key in YAML `orchestration.strategy`). This is confusing and will get worse.

Pick:

- `orchestration.strategy` — registry key (orchestration shape)
- `orchestration.prompt_strategy` — prompt variant (`zero_shot` / `few_shot` / `cot_self`)
- Inside workflow constructors, the parameter is named `prompt_strategy`, not `strategy`

Rename the existing workflow-level `strategy` parameter to `prompt_strategy` everywhere.

### ~~Acceptance~~ (shipped)

- ~~`python -m harness.workflows.registry --list` shows exactly the new (shorter) set of names.~~
- ~~Adding a new prompt variant `system_self_consistency.md` requires only: adding the file under `harness/prompts/`, an entry to `_PROMPT_FILES` in `harness/workflows/utils.py`, and `orchestration.prompt_strategy: self_consistency` in YAML — no changes to the registry, no new builders.~~
- ~~All existing YAML configs in `harness/configs/` are rewritten and still produce equivalent runs.~~
- ~~`config_attributes()` from Change 1 correctly reports `ema.orchestration.prompt_strategy` independently of `ema.orchestration.strategy`.~~

### ~~Estimated effort~~ — done

---

## Suggested execution order

1. **Change 3 first** if you want the cleanest possible attribute keys in Change 1 (avoids stamping the redundant `simple_rag_zero` shape and having to rename later).
2. **Change 1 second.** This is the highest-leverage change for your stated goal (trace and rate configurations).
3. **Change 2 third.** This unlocks new configurations to *put on* the traces, but only matters once Change 1 makes them queryable.

If you'd rather not do them in dependency order, the alternative is Change 1 → Change 2 → Change 3 and pay a small cost in retroactively cleaning up attribute keys.

## Cross-cutting requirements

- Each change should land as its own work unit in `.claude/work/` per the existing project convention.
- Existing tests in `tests/` must continue to pass after each change. Where a change touches code that has no current test coverage, add at least one new test that exercises the new code path.
- Update `DECISIONS.md` with a short entry per change explaining what changed and why.
- ~~Update `docs/RETRIEVAL_PIPELINE.md` after Change 2~~ — obsolete: that doc and `build_retrieve_fn` are superseded by the Neo4j retrieval refactor (see `docs/RETRIEVAL.md`).
- Update `README.md` stack table only if the workflow framework or tracing tool changes — which it doesn't, in any of these.
