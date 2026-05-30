# Harness refactors — three changes to make config exploration and tracing first-class

This document specifies three changes to `harness/` that, together, make it possible to:

1. Filter and group Phoenix traces by configuration (strategy, retrieval mode, reranker, prompt variant, LLM)
2. Compose any orchestration strategy with any retrieval ablation without code changes
3. Add a new prompt variant by editing YAML, not the workflow registry

Each change is independently shippable. Order matters: **Change 1** is highest ROI and unblocks meaningful trace analysis. **Change 2** removes a real compositional limitation. **Change 3** is cleanup but removes redundancy that would otherwise grow.

No backward compatibility is required — old YAML config names and registry keys can be hard-renamed.

> ⚠️ **Status (2026-05-30).** All three changes shipped. **Change 2** (`build_retrieve_fn`
> composing retrieval ablations) is **superseded** by the LlamaIndex-first retrieval refactor:
> workflows are being re-seamed to a LlamaIndex retriever from `harness.indexing` (LIR-009),
> and the `build_retrieve_fn`/ablation machinery is part of the old stack being removed
> (LIR-012). **Change 1** (Phoenix span stamping) and **Change 3** (`prompt_strategy` YAML)
> remain in effect. See [`docs/RETRIEVAL.md`](docs/RETRIEVAL.md).

---

## Change 1 — Stamp configuration onto Phoenix span attributes

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

### Acceptance

- After running any benchmark eval, opening the Phoenix UI and filtering on `ema.orchestration.strategy == "crag" AND ema.retrieval.reranker == "sme"` returns exactly the expected runs.
- Existing thumbs-up/down feedback flow in `app.py` continues to work unchanged.
- A `pytest` test exists that mocks Phoenix and asserts the expected attribute keys are set on the root span for at least one workflow.
- `PHOENIX_DISABLED=1` does not cause any test to fail.

### Estimated effort

One evening (~3 hours).

---

## Change 2 — Push retrieval-layer ablations into a shared factory

### Problem

Today, `run_eval.py` builds a `retrieve_fn` closure (lines ~100–164) that wraps the base retriever with optional query expansion (A1), topic filtering (A2), and LLM reranking (A3/A4). But the workflows in `harness/workflows/*.py` call `retrieve_with_config(self._config, self._index, ...)` **directly**, bypassing this closure.

Consequence: **A3 reranker cannot compose with CRAG, ReAct, or any other workflow.** The ablation stack is only applied during the standalone retrieval eval, not during orchestration. This is a real architectural limit on the configuration surface, masquerading as a code-organization issue.

It also means `app.py` (Chainlit) builds retrieval one way and `run_eval.py` builds it another way, with no shared source of truth — exactly the kind of drift that makes ablations un-reproducible.

### Approach

Introduce a factory `build_retrieve_fn(ret_config, abl_config, index, hier_index=None)` in `harness/retrieve.py`. The factory returns a `Callable[[str], list[RetrievalResult]]` that internally applies, in order:

1. Query expansion (A1) if enabled
2. Base retrieval (dense / bm25 / hybrid, flat / recursive / hierarchical)
3. Topic filter (A2) if enabled
4. Reranker (A3/A4) if enabled

Both `app.py` and `run_eval.py` call this factory. Workflows accept an optional `retrieve_fn` parameter in their constructor; when provided, they use it instead of building one from `RetrievalConfig` alone. The workflow registry builder passes `retrieve_fn` through `**kwargs`.

### Files to touch

- `harness/retrieve.py` — add `build_retrieve_fn` factory; define an `AblationConfig` dataclass to carry `query_expansion`, `topic_filter`, `reranker` settings parsed from the YAML `ablation:` section
- `harness/run_eval.py` — replace the inline `retrieve_fn` construction with a call to `build_retrieve_fn`; pass the resulting callable into `get_workflow(...)`
- `app.py` — call `build_retrieve_fn` once at session start and pass the result into workflow construction (the Chainlit `ChatSettings` for ablation toggles can come later; for now, drive from a default `AblationConfig` or read from the same YAML file)
- `harness/workflows/registry.py` — accept `retrieve_fn` in `get_workflow()` and forward via `**kwargs`
- Every workflow class — accept optional `retrieve_fn` in `__init__`; when provided, call it instead of `retrieve_with_config(self._config, self._index, question)`

### Design constraints

- `RetrievalConfig` stays focused on **retrieval semantics** (strategy, mode, k, recursive/hierarchical sub-configs). It does **not** absorb ablation flags.
- `AblationConfig` is a separate dataclass that lives alongside `RetrievalConfig`. The YAML schema is unchanged — the `retrieval:` and `ablation:` sections continue to be parsed independently and combined only inside `build_retrieve_fn`.
- The factory must be cheap to call but the *returned callable* must be efficient on repeated invocation (BM25 retriever caching already in `harness/retrieve.py` should still apply — verify the cache key still hits).
- When `retrieve_fn` is not provided to a workflow, it falls back to the current behaviour (`retrieve_with_config(self._config, self._index, ...)`). This keeps existing tests green and lets the migration be incremental.
- Make sure the `config_attributes()` from Change 1 reflects the ablation flags actually in use — when `retrieve_fn` is injected, the workflow should still be able to report `ema.retrieval.reranker` etc. Easiest path: have `build_retrieve_fn` attach the resolved `AblationConfig` as an attribute on the returned callable (e.g. `retrieve_fn.ablation_config = abl_cfg`), and have the workflow's `config_attributes()` read from it.

### Acceptance

- A new YAML config combining `orchestration.strategy: crag` with `ablation.reranker: sme` runs end-to-end and produces sensible answers.
- The `retrieve_fn` used by `app.py` and `run_eval.py` is provably the same object (same factory, same defaults) for any given config.
- Existing baseline_a0, ablation_a_a1 through a_a5 configs run unchanged and produce the same retrieval metrics as before the refactor (within numerical tolerance).
- Phoenix spans correctly reflect the active ablation flags for orchestration runs (depends on Change 1).

### Estimated effort

One to two evenings (~4–6 hours). Most of the work is moving code, not writing new logic.

---

## Change 3 — Collapse `simple_rag_*` and `crag_*` into base entries with `prompt_strategy` as a YAML field

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

### Acceptance

- `python -m harness.workflows.registry --list` shows exactly the new (shorter) set of names.
- Adding a new prompt variant `system_self_consistency.md` requires only:
  1. Adding the file under `harness/prompts/`
  2. Adding an entry to `_PROMPT_FILES` in `harness/workflows/utils.py`
  3. Setting `orchestration.prompt_strategy: self_consistency` in YAML
  
  No changes to the registry, no new builders.
- All existing YAML configs in `harness/configs/` are rewritten and still produce equivalent runs.
- `config_attributes()` from Change 1 correctly reports `ema.orchestration.prompt_strategy` independently of `ema.orchestration.strategy`.

### Estimated effort

One evening (~3 hours), mostly mechanical edits across YAML configs and propagating the renamed parameter.

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
