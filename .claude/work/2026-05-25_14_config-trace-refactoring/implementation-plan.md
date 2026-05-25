# Harness Config/Trace Refactoring — Implementation Plan

**Work unit:** 2026-05-25_14_config-trace-refactoring  
**Source:** `HARNESS_REFACTORS.md`  
**Estimated total:** ~18 hours across 12 tasks  
**Execution order:** Change 3 → Change 1 → Change 2

---

## Project Overview

Three self-contained changes to `harness/` that together make configuration exploration and tracing first-class:

1. **Change 3** — Collapse the `simple_rag_zero/few/cot` registry clones into a single `simple_rag` entry driven by a `prompt_strategy` YAML field. Eliminates the registry/prompt coupling that would otherwise force double work when renaming span attributes.

2. **Change 1** — Stamp the active configuration (strategy, prompt variant, retrieval mode, k, reranker, model) onto the root Phoenix span before each workflow run. Enables `ema.orchestration.strategy == "crag" AND ema.retrieval.reranker == "sme"` queries in Phoenix UI.

3. **Change 2** — Extract the inline `retrieve_fn` closure from `run_eval.py` into a shared `build_retrieve_fn(ret_config, abl_config, index)` factory in `harness/retrieve.py`. Enables A3 reranking to compose with CRAG/ReAct. Eliminates drift between `app.py` and `run_eval.py` retrieval paths.

No backward compatibility required — old YAML config names and registry keys are hard-renamed.

---

## Technical Architecture

### After Change 3: registry shape

```
WORKFLOW_REGISTRY:
  simple_rag       ← was simple_rag_zero/few/cot (prompt_strategy from YAML)
  crag
  react
  summarize_rag
  crag_summarize
  crag_review
  react_review
```

YAML orchestration block:
```yaml
orchestration:
  strategy: simple_rag
  prompt_strategy: cot_self   # new field; zero_shot | few_shot | cot_self
```

### After Change 1: span attribute contract

Every `WorkflowRunner.ainvoke` call stamps these on the root OTel span (before workflow runs):
```
ema.orchestration.strategy     e.g. "crag"
ema.orchestration.prompt_strategy  e.g. "zero_shot"
ema.retrieval.strategy         e.g. "flat"
ema.retrieval.mode             e.g. "hybrid"
ema.retrieval.k                e.g. 10
ema.retrieval.reranker         e.g. "none" | "sme" | "generic"
ema.retrieval.query_expansion  bool
ema.retrieval.topic_filter     e.g. "none" | "keyword" | "concept"
ema.llm.agent_model            model name
ema.run.id                     UUID per interaction
ema.run.source                 "chainlit" | "eval" | "cli"
```

Source: workflow's `config_attributes()` method + `run_id`/`source` from input dict.

### After Change 2: shared retrieval factory

```python
# harness/retrieve.py (new)
@dataclass
class AblationConfig:
    query_expansion: dict = field(default_factory=dict)
    topic_filter: dict = field(default_factory=dict)
    reranker: str | None = None
    reranker_max_chunks: int = 5

    @classmethod
    def from_yaml(cls, abl_dict: dict) -> "AblationConfig": ...

def build_retrieve_fn(
    ret_config: RetrievalConfig,
    abl_config: AblationConfig,
    index: Any,
    hier_index: Any | None = None,
) -> Callable[[str], list]:
    ...
    fn.ablation_config = abl_config   # for config_attributes()
    return fn
```

Both `app.py` (once per session) and `run_eval.py` (once per run) call this factory. Workflows accept `retrieve_fn` kwarg and use it when provided, falling back to `retrieve_with_config()` otherwise.

---

## Task Execution Plan

### Change 3 — Registry Collapse (Tasks TRACE-001 → TRACE-003)

**TRACE-001** — Rename `strategy` → `prompt_strategy` in workflow constructors + remove 3 redundant builders
- `simple_rag.py`: rename `__init__` param; update `StopEvent` result key (already `prompt_strategy`)
- `crag.py`: rename `__init__` param
- `summarize_rag.py`: rename `__init__` param
- `composites.py`: propagate `prompt_strategy` through `build_crag_summarize`, `build_crag_review`
- `registry.py`: remove `_build_simple_rag_zero/few/cot`; add `_build_simple_rag(index, llm, *, prompt_strategy="zero_shot", **kw)`; update docstring; update `WORKFLOW_REGISTRY`

**TRACE-002** — Wire `run_eval.py` and `app.py` to new YAML field
- `run_eval.py`: `orch_cfg.get("prompt_strategy", "zero_shot")` → passed to `get_workflow()`
- `app.py`: map `ChatProfile` to `(strategy, prompt_strategy)` tuple; pass both to `get_workflow()`

**TRACE-003** — Rewrite 10 YAML configs
- 9 `ablation_c_*.yaml`: add `prompt_strategy: zero_shot/few_shot/cot_self`; change `strategy` to `simple_rag`
- `workflow_simple_rag.yaml`: same treatment
- `DECISIONS.md`: add entry for registry collapse

---

### Change 1 — Phoenix Span Attributes (Tasks TRACE-004 → TRACE-007)

**TRACE-004** — Add `config_attributes()` to all 6 workflow classes
- Minimum set per class in acceptance criteria (see state.json)
- `simple_rag.py`: reads `self._config` (RetrievalConfig) for retrieval fields
- `crag.py`: adds `ema.crag.max_cycles`
- `react_native.py`: strategy key `react`
- `composites.py`: outer + delegated workflow keys

**TRACE-005** — `WorkflowRunner.ainvoke` stamps span
```python
async def ainvoke(self, inputs: dict) -> dict:
    span = opentelemetry.trace.get_current_span()
    if span.is_recording():
        attrs = getattr(self._wf, "config_attributes", None)
        if attrs is None:
            log.warning("Workflow %s has no config_attributes() — skipping span stamp", ...)
        else:
            for k, v in attrs().items():
                span.set_attribute(k, v)
        if run_id := inputs.get("run_id"):
            span.set_attribute("ema.run.id", run_id)
        if source := inputs.get("source"):
            span.set_attribute("ema.run.source", source)
    return await self._wf.run(**inputs)
```

**TRACE-006** — Pass `run_id`/`source` through invocation inputs
- `app.py`: `runner.ainvoke({"question": ..., "run_id": run_id, "source": "chainlit"})`
- `run_eval.py`: `runner.invoke({"question": ..., "run_id": cfg["run_id"], "source": "eval"})`

**TRACE-007** — pytest test (`tests/test_span_attributes.py`)
- Three tests: recording span → attributes stamped; non-recording → silent; missing method → warning only

---

### Change 2 — Shared Retrieval Factory (Tasks TRACE-008 → TRACE-012)

**TRACE-008** — `AblationConfig` + `build_retrieve_fn` in `harness/retrieve.py`
- Lift exact logic from `run_eval.py` lines 100–164 into the factory
- Add `.ablation_config` attribute on returned callable

**TRACE-009** — `retrieve_fn` parameter in all workflow `__init__`
- Add `retrieve_fn: Callable | None = None`; store as `self._retrieve_fn`
- In retrieve steps: `results = self._retrieve_fn(q) if self._retrieve_fn else retrieve_with_config(self._config, self._index, q)`

**TRACE-010** — Registry + run_eval.py + app.py call sites
- `registry.get_workflow()`: accept + forward `retrieve_fn`
- `run_eval.py`: `abl_config = AblationConfig.from_yaml(cfg.get("ablation", {}))` → `retrieve_fn = build_retrieve_fn(ret_config, abl_config, index)` → pass to `get_workflow()`
- `app.py`: `retrieve_fn = build_retrieve_fn(ret_config, AblationConfig(), index)` in `on_chat_start`

**TRACE-011** — Expose `AblationConfig` in `config_attributes()`
- When `self._retrieve_fn` has `.ablation_config`, read `reranker`, `query_expansion`, `topic_filter` from it
- Fall back to RetrievalConfig defaults otherwise

**TRACE-012** — Docs
- `RETRIEVAL_PIPELINE.md`: new "Shared retrieval factory" section
- `DECISIONS.md`: entries for all three changes

---

## Quality Assurance

- Each task leaves `pytest tests/` green before moving on
- TRACE-003: run `python -m harness.run_eval --config harness/configs/ablation_c_mid_zero.yaml --dry-run` (or equivalent smoke test) to verify YAML parsing
- TRACE-010: new YAML config `harness/configs/test_crag_sme.yaml` with `orchestration.strategy: crag` + `ablation.reranker: sme` as end-to-end acceptance check
- TRACE-007: deterministic unit test (no LLM calls, no real index required)

---

## Dependencies

```
TRACE-001
├── TRACE-002 → TRACE-003 → TRACE-008 → TRACE-009 → TRACE-010
└── TRACE-004 → TRACE-005 → TRACE-006
                           └── TRACE-007

TRACE-010 + TRACE-004 → TRACE-011 → TRACE-012
```

Critical path: TRACE-001 → TRACE-004 → TRACE-005 → TRACE-010 → TRACE-011 → TRACE-012
