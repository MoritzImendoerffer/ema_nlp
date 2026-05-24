# Instructions for Claude Code — prioritized fix list

This document is the working brief for Claude Code on the `ema_nlp` project. Findings are listed in **criticality order** — work top-down. Each finding includes: the diagnosis, why it matters, the proposed fix, and what NOT to do.

**Project stance:** Early-stage research code. Backwards compatibility is **not** required. Breaking changes are welcome if they simplify the system. Question legacy code aggressively.

**Working style requirements (from user preferences):**
- Discuss design before writing code.
- Start simple. Don't add features that weren't asked for.
- Keep the user in the loop. Surface trade-offs.

---

## P1 — Architectural cleanup

### P1.1 Remove dead `judge.model` field from YAML configs

**Diagnosis.** Several configs have `judge: model: claude-haiku-4-5-20251001`. The `Judge` class reads the `judge` role from `models.yaml` (currently `claude_opus`) and ignores this YAML field. It's dead weight and misleading.

**Proposed fix.** Delete `judge.model` (or the entire `judge:` block where `enabled: false`) from all 20 YAML configs that contain it. Keep `judge.enabled` and `judge.sample_fraction` where used.

**Do not.** Add model-field parsing to `Judge`. Role bindings in `models.yaml` are the single source of truth.

---

## P2 — Polish and UX

### P2.1 Build a Streamlit/Gradio orchestration dashboard

**Diagnosis.** No interactive UI for switching between workflows/retrieval modes/ablations. Chainlit runs one fixed workflow per session. The user explicitly wants this for "play with configurations" exploration.

**On n8n / visual workflow builders specifically:** ruled out. n8n is built for sync request/response between SaaS APIs, not for async LlamaIndex workflows with loops and in-memory state. Langflow/Flowise are closer but they're builders for new graphs, not visualizers for an existing typed registry.

**Recommendation: Streamlit.** Reads `WORKFLOW_REGISTRY` for the dropdown, exposes the same `RetrievalConfig` toggles as YAML configs, calls the existing `WorkflowRunner.invoke()`. ~300-500 lines.

**Sketch:**

```
┌──────────────────────────────────────────────────────────┐
│ Sidebar:                    │  Main:                     │
│ ─────────────               │  ─────                     │
│ Workflow [react ▾]          │  Question: [_____________] │
│ Retrieval mode [hybrid ▾]   │            [Run]           │
│ k = [10]                    │                            │
│ Strategy [flat ▾]           │  Answer:                   │
│                             │  ...                       │
│ Ablations:                  │                            │
│ ☐ A1 query expansion        │  Cited sources:            │
│ ☐ A2 topic filter (keyword) │  - qa_id_1                 │
│ ☐ A3 SME reranker           │  - qa_id_2                 │
│                             │                            │
│ ☐ Run on all 4 workflows    │  Trajectory (if ReAct):    │
│   in parallel               │  Step 1: ema_search(...)   │
│                             │  Step 2: get_qa_by_id(...) │
│ Model tier [mid ▾]          │                            │
│                             │  [Rate 1-5: ▢▢▢▢▢]         │
└──────────────────────────────────────────────────────────┘
```

**Design questions for the user before building:**
1. Should this replace Chainlit or live alongside it? (Recommendation: replace. Chainlit's session-pinned workflow is the limitation we're trying to escape.)
2. Should "run on all 4 in parallel" show all answers stacked, or a comparison table? (Probably stacked for v1.)
3. Should it write rated runs back to the same query cache and Phoenix as the CLI? (Yes — single source of truth for HITL data.)
4. Is there appetite to vendor the Phoenix trace tree view into the dashboard, or stay with the existing Phoenix UI in a side tab? (Probably side tab — don't reinvent Phoenix.)

**Do not.** Build this before the HITL loop produces enough labeled data to be worth exploring in the dashboard.

---

### P2.2 Annotation queue automation

Phoenix has annotation queues. `docs/SETUP.md` describes creating them manually via the UI. Worth adding a script (`scripts/setup_phoenix_annotations.py`) that creates the annotation configs and queues via the Phoenix REST API — one-shot setup for new machines.

---

## P3 — Optional, only if you have time

### P3.1 Lift computation harness

`harness/compute_lift.py` works but requires manually pairing closed-book and open-book runs. A wrapper that runs the closed-book config automatically when given the open-book config (zeroing out retrieval) would be ergonomic.

### P3.2 Skip token in workflow generation

When the LLM in `react_native.py` emits a malformed action, the agent eats an iteration. Add a "retry once with explicit format reminder" before counting it.

---

## What to do first — concrete starting sequence

1. **P1.1** — quick cleanup: delete stale `judge.model` field from configs.
2. **P2.1** — Streamlit dashboard is the next high-value UX item. Discuss design with user first.
3. **Build label session data** — run `harness/label_session.py` sessions to accumulate ≥ 50 rated examples. This unblocks Ablation B and DSPy.

---

## Files Claude Code should treat as sensitive (read-only by default)

- `corpus/corpus.jsonl` — versioned data, do not regenerate without user OK.
- `benchmark/benchmark.jsonl` — the eval set. Modifying it invalidates all previous run comparisons. Absolutely do not touch.
- `harness/judges/*.md` — judge prompts. Changing wording changes scores. Discuss before editing.
- `harness/prompts/few_shot_examples.md`, `relevance_rubric_sme.md` — SME-authored content. Same caveat.
- `~/.myenvs/ema_nlp.env` — credentials. Never read, never write.

## Files Claude Code should feel free to refactor

- Anything under `harness/workflows/` — the registry abstracts callers, refactors are local.
- Anything under `harness/ablations/` — same.
- `harness/run_eval.py` — but watch out for the comparison-report generator script which reads its output format.
- Anything under `scripts/` except `scripts/sync_mongo.sh`, `scripts/setup.sh`, `scripts/tag_concepts.py`.
- All YAML configs in `harness/configs/` — but if you delete a field, delete it from ALL configs.
