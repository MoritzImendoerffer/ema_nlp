# Harness refactoring — implementation plan

**Work unit:** `2026-05-22_11_harness-refactoring`  
**Created:** 2026-05-22  
**Source:** `ema_nlp_review.md` (v2) + `CLAUDE_GUIDANCE.md`  
**Status:** Planning complete — start at REFACT-001

---

## Project overview

Four root problems drive this refactoring:

1. **Split pipeline (P0).** `harness/run_eval.py` has its own answer-generation path via `answer_gen.py` that bypasses all nine registered workflows. CRAG, ReAct, composites are invisible to the benchmark.
2. **Naïve CRAG grader (P0).** Single-word `sufficient/insufficient` LLM judgment is yes-biased and never grounds the rewrite loop in actual missing information.
3. **Role/model conflation (P1).** `tier_id` determines both which model and which role. You can't swap the grader to a local model without touching the agent.
4. **Shallow HITL (P1).** A 👍/👎 button after full pipeline completion is not step-level review. Phoenix has annotation queues; the code doesn't use them.

The fix is sequenced across 6 weeks so the tree stays runnable after every task.

---

## Design decisions (confirmed 2026-05-22)

| Decision | Choice |
|---|---|
| `tier_id` API break | Break cleanly in Week 2 — no backward-compat alias |
| Phoenix label vocabulary | Start with `step_quality` + `answer_quality` only |
| Phoenix hosting | Home PC (Vienna) always-on; Elitebook connects via Tailscale |
| Eval design | Stacked, not orthogonal: Ablation A fixes workflow at `simple_rag_zero`; workflow axis fixes retrieval at A0+ |
| CRAG comparability | Breaking old CRAG baseline is acceptable |
| Trace explorer | Phoenix annotation queues — no custom build |

---

## Technical architecture

### After Week 1 — unified answer-generation path

```
harness/configs/<run>.yaml
  orchestration:
    strategy: simple_rag_zero   # or crag, react, …
    # tier_id removed in Week 2

run_eval.py
  ├── retrieve_fn()              ← unchanged (retrieval eval: Recall@k, etc.)
  └── get_workflow(strategy, index, llm, retrieval_config)
           └── runner.invoke({"question": …})
               └── {"answer_text", "docs", "prompt_strategy"}
```

`answer_gen.py` is deleted. `answer_generation:` YAML key is gone.

### After Week 2 — role-based LLM config

```
harness/configs/models.yaml
  models:
    claude_haiku: {provider: anthropic, model_id: …}
    claude_opus:  {provider: anthropic, model_id: …}
    olmo_32b:     {provider: together_ai, …}
    local_qwen32: {provider: openai_compatible, api_base: http://localhost:11434/v1, …}
  roles:
    agent:    claude_haiku
    grader:   claude_haiku      # swap to local_qwen32 for a run via role_overrides:
    rewriter: claude_haiku
    reranker: claude_haiku
    judge:    claude_opus
    reviewer: claude_opus

get_llm("agent")    → Haiku
get_llm("grader")   → Haiku (or local_qwen32 via override)
get_llm("judge")    → Opus
```

`tier_id`, `TIER_MID`, `TIER_FRONTIER`, `TIER_OLMO`, `TierId` removed everywhere.

### After Week 3 — native ReAct with per-step spans

```
StartEvent → think → ThoughtEvent
ThoughtEvent → act → ActionEvent | FinishEvent
ActionEvent → observe → ObservationEvent
ObservationEvent → think (loop, max 5 iterations)
FinishEvent → StopEvent
```

Each step is its own Phoenix span, independently annotatable with `step_quality`.  
Old `react` workflow accessible as `react_legacy`.

### After Week 4 — annotation export pipeline

```
Phoenix (live labels)
    └── harness/hitl/export_annotations.py --since 2026-05-22
            └── ~/Nextcloud/Datasets/ema_nlp/annotations/YYYY-MM-DD.jsonl
```

### After Week 5 — cleanup

- `Doc` dataclass gone; `TextNode` end-to-end
- BM25 built once per session
- A3/A4 as `NodePostprocessor`
- `results/` → Nextcloud symlink
- README describes "agentic RAG", not "Graph RAG"

---

## Task execution plan

### Week 1 — Unify eval and orchestration

| Task | Description | Hours | Depends on |
|------|-------------|-------|------------|
| REFACT-001 | Migrate ablation_c configs to `orchestration:` block | 1h | — |
| REFACT-002 | Wire `run_eval.py` answer generation to workflow registry | 2h | 001 |
| REFACT-003 | Delete `answer_gen.py`; update judge to use workflow docs | 1h | 002 |
| REFACT-004 | Confirm baselines A0 and A0+ reproduce through workflow path | 2h | 003 |

**Config schema change for ablation_c configs:**
```yaml
# Before
answer_generation:
  enabled: true
  strategy: zero_shot
  tier_id: mid

# After
orchestration:
  strategy: simple_rag_zero   # zero_shot→simple_rag_zero, few_shot→simple_rag_few, cot_self→simple_rag_cot
```

**run_eval.py change (answer gen block):**
```python
# Before
from harness.answer_gen import generate_answer
gen = generate_answer(question, docs, strategy=ag_strategy, tier_id=ag_tier)

# After
from harness.workflows.registry import get_workflow
runner = get_workflow(orch_strategy, index=index, llm=get_llm("agent"), retrieval_config=ret_config)
result = runner.invoke({"question": item["question"]})
```

**Week 1 definition of done:** `pytest tests/` passes; `python -m harness.run_eval --config harness/configs/ablation_c_mid_zero.yaml` runs to completion; `run_summary.md` written.

---

### Week 2 — Fix CRAG + role-based LLM config

| Task | Description | Hours | Depends on |
|------|-------------|-------|------------|
| REFACT-005 | Restructure `models.yaml` into `models:` + `roles:` sections | 1h | 004 |
| REFACT-006 | Refactor `harness/llms.py` — `get_llm(role)` API; break `tier_id` | 2h | 005 |
| REFACT-007 | Migrate all `tier_id` call sites to `get_llm(role)` | 2h | 006 |
| REFACT-008 | Fix CRAG grader: per-doc JSON scoring + `missing_facts` | 3h | 007 |

**CRAG grader change (crag.py):**
```python
# New _GRADE_SYSTEM prompt — per-doc 0/1/2 with missing_facts JSON
# Trigger rewrite if: no doc scored 2 OR missing_facts is non-empty
# Pass missing_facts to rewrite prompt so the query targets the actual gap
```

**REFACT-007 call site inventory:**
- `run_eval.py` — `get_llm_model()` / `tier_id` in orchestration block → `get_llm("agent")`
- `judge.py` — direct `anthropic.Anthropic()` client → `get_llm("judge")`
- `a3_reranker.py`, `a4_reranker.py` — direct SDK → `get_llm("reranker")`
- `registry.py` — `tier_id` kwarg in `get_workflow()` → removed

**Week 2 definition of done:** `pytest tests/` passes; CRAG run on 3 T3 questions shows rewrite loop triggered at least once (instead of always grading sufficient).

---

### Week 3 — Native ReAct + Phoenix annotation setup

| Task | Description | Hours | Depends on |
|------|-------------|-------|------------|
| REFACT-009 | Build `harness/workflows/react_native.py` with per-step events | 4h | 007 |
| REFACT-010 | Register `react_native`; rename legacy → `react_legacy` | 1h | 009 |
| REFACT-011 | Document Phoenix annotation setup in `docs/SETUP.md` | 1h | 009 |

**ReAct event graph:**
```
StartEvent → think → ThoughtEvent
ThoughtEvent → act → ActionEvent (tool call) | FinishEvent (no tool needed)
ActionEvent → observe → ObservationEvent
ObservationEvent → think (loop)
FinishEvent → StopEvent
```

**Manual Phoenix setup (REFACT-011 documents this — no code):**
- Create annotation config `step_quality`: categorical {`good`, `suboptimal`, `wrong`} — attach to tool-call spans and thought spans
- Create annotation config `answer_quality`: 1–5 scale + freeform reason — attach to root spans
- Create annotation queues: one per strategy ("recent CRAG", "recent react")

**Week 3 definition of done:** `react_native` registered and answering questions in Chainlit; Phoenix shows separate think/act/observe spans for each step.

---

### Week 4 — Annotation export + first labelling session

| Task | Description | Hours | Depends on |
|------|-------------|-------|------------|
| REFACT-012 | Create `harness/hitl/` package skeleton | 1h | 010 |
| REFACT-013 | Write `harness/hitl/export_annotations.py` — Phoenix → Nextcloud JSONL | 3h | 012 |
| REFACT-014 | First SME labelling session + runtime interrupt decision | 3h | 013 |

**export_annotations.py output schema:**
```json
{
  "trace_id": "…",
  "span_id": "…",
  "span_name": "tool_call.ema_search",
  "input": {…},
  "output": {…},
  "labels": {"step_quality": "wrong"},
  "reason": "retrieved genotoxicity impurities instead of NDMA-specific limit",
  "annotated_by": "moritz",
  "annotated_at": "2026-05-28T19:00:00Z"
}
```

**Week 4 definition of done:** 5 questions × 3 strategies labelled in Phoenix; JSONL written to `~/Nextcloud/Datasets/ema_nlp/annotations/`; decision made on runtime interrupt.

---

### Week 5 — Cleanup pass

| Task | Description | Hours | Depends on |
|------|-------------|-------|------------|
| REFACT-015 | Cache BM25 retriever per session | 1h | 004 |
| REFACT-016 | Drop `Doc` dataclass; use `TextNode` end-to-end | 3h | 010 |
| REFACT-017 | Promote A3/A4 rerankers to `NodePostprocessor` | 2h | 016 |
| REFACT-018 | Move EMA acronym hint from `react.py` to `acronym_dict.yaml` | 1h | 010 |
| REFACT-019 | Move `results/` to Nextcloud; add repo symlink | 1h | 004 |
| REFACT-020 | Fix README framing + RETRIEVAL_PIPELINE.md A3/A4 section | 1h | — |

**REFACT-015 and 016 can be done in parallel.** REFACT-017 depends on 016 (TextNode interface). REFACT-018, 019, 020 are independent.

**Week 5 definition of done:** `pytest tests/` passes; `bash run_ui.sh` answers a question; `run_eval.py` smoke test succeeds; no `Doc` import anywhere.

---

### Week 6 — Ablation comparison + write-up

| Task | Description | Hours | Depends on |
|------|-------------|-------|------------|
| REFACT-021 | Run full Ablation A comparison (A0–A5) on `simple_rag_zero` | 2h | all week 5 |
| REFACT-022 | Run workflow axis comparison on A0+ retrieval | 2h | 021 |
| REFACT-023 | Write T1/T2/T3/T4 per-strategy comparison report | 2h | 022 |
| REFACT-024 | SME failure-mode breakdown + v2 scope decision | 2h | 023 |

**Week 6 definition of done:** Comparison report written; v2 scope decided in `DECISIONS.md`; `ROADMAP.md` Phase 3+ updated.

---

## Quality assurance

After every task:
- `pytest tests/` must pass
- `python -m harness.run_eval --config harness/configs/baseline_a0plus.yaml` must succeed
- `bash run_ui.sh` must start and answer a question

After REFACT-004: baseline numbers must reproduce within ±0.02 of pre-refactor.  
After REFACT-007: run 3 questions through CRAG and confirm rewrite loop triggers at least once.  
After REFACT-009: run 3 questions through `react_native` in Chainlit; check Phoenix for per-step spans.

---

## Sensitive files — extra care required

- `harness/configs/*.yaml` — all 20 configs touched in REFACT-001/007/019/022. Schema migration must be coordinated; no config left in broken intermediate state.
- `harness/models.py` — `TierId`, `TIER_MID` etc. removed in REFACT-007. The smoke-test `__main__` block must be updated.
- `DECISIONS.md` — append new entries after REFACT-004, 005, 009, 024. Never rewrite existing entries.

---

## v2 scope (post-six-weeks)

Decided after REFACT-024 based on evidence:
- **Ablation B (process rewards):** Only if Phoenix labelling reveals systematic failure patterns worth learning from.
- **DSPy:** Only if ≥50 rated trajectories exist.
- **Graph RAG:** Only if `cross_refs` traversal proves insufficient on T3 questions.
