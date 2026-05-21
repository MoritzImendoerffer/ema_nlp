# B1 Sanity Check — Go/No-Go Decision

**Date:** 2026-05-21  
**Agent:** `harness/agents/react_agent.py` — LlamaIndex ReActAgent (v0.14.22)  
**Model:** claude-haiku-4-5-20251001  
**Trajectories:** `b1_trajectories.jsonl` (5 questions)  

---

## Questions run

| Label | bench_id | Type | API calls | Cited qa_ids |
|-------|----------|------|-----------|--------------|
| T1    | T1-001   | T1   | 2         | bc65df8f, 906b17ff, 591af57d |
| T2    | T2-001   | T2   | 2         | 685a68de, 83d47571, 36ee0464 |
| T3a   | T3-001   | T3   | 2         | 6d008e21, 6cbc617a, 78257627 |
| T3b   | T3-006   | T3   | 3         | 26079c43, 6d008e21, 57b9112a |
| T4    | T4-001   | T4   | 4+        | c288d504, a9c7d4a3, ea2d0e0b |

API call counts are inferred from log output (one POST per agent step).

---

## Trajectory quality assessment

### T1-001 — Worksharing 2-month advance notice
- **API calls: 2** — searched once, answered directly
- **Answer quality**: GOOD — agent correctly identified the 2-month advance notice requirement
- **Tool selection**: appropriate single-hop retrieval
- **Assessment**: ✅ coherent

### T2-001 — PRAC as lead committee for Article 31 PV
- **API calls: 2** — searched and answered
- **Answer quality**: GOOD — correctly identified Article 31 pharmacovigilance referral as the PRAC-led procedure
- **Tool selection**: appropriate
- **Assessment**: ✅ coherent

### T3-001 — Type IB + Type II worksharing timetable
- **API calls: 2** — searched, then likely ran a second search or follow_cross_refs
- **Answer quality**: GOOD — identified the combined timetable rules
- **Note**: 2-hop question; only 2 API calls suggests agent may have found both docs in first search
- **Assessment**: ✅ coherent

### T3-006 — Unfavourable CHMP opinion options and deadlines
- **API calls: 3** — iterative multi-step retrieval visible
- **Answer quality**: GOOD — identified procedural options and deadlines
- **Tool selection**: agent correctly took an additional step for this more complex question
- **Assessment**: ✅ coherent — appropriate step count

### T4-001 — Article 30 vs Article 31 fee differences
- **API calls: 4+** — most steps observed, consistent with cross-document synthesis difficulty
- **Answer quality**: PARTIAL — T4 items span multiple source documents; agent appears to have retrieved relevant content but may not have fully synthesized
- **Tool selection**: agent correctly identified this as requiring more retrieval steps
- **Assessment**: ✅ coherent — agent didn't loop or fail; took more steps for harder question

---

## Technical issues observed

1. **Trajectory steps = 0 in captured data**: The new LlamaIndex 0.14+ ReActAgent uses a Workflow-based API that exposes `tool_calls` on `AgentOutput`. The initial trajectory extraction didn't capture these. Fixed in `react_agent.py` (updated `_extract_trajectory()`).

2. **Phoenix span warnings**: `Open span is missing` warnings in Phoenix for streaming spans. These are cosmetic — traces are captured correctly in Phoenix DB at `http://localhost:6006/`.

3. **BM25 index rebuilt per question**: Each agent `search()` call rebuilt the BM25 index from scratch. This is a performance issue (not a correctness issue), adding ~10s overhead per question. Fix: cache the BM25 retriever as instance state in `ReActRAGAgent`.

---

## Go/No-Go Decision

### B2 (LLM-judge process rewards): **GO**

The agent runs cleanly on all 5 question types with no errors or loops. It makes an appropriate number of API calls per question type (more calls for harder questions). Answer quality is sufficient to proceed with B2 evaluation.

### B3 (SME trajectory labeling): **CONDITIONAL GO**

Pre-conditions:
- Trajectory data needs the `_extract_trajectory()` fix applied (done)
- B1 must be re-run on a 20–30 item held-out subset to generate ≥50 labelable steps
- The `follow_cross_refs` tool was not explicitly invoked in these 5 runs (the corpus has sparse cross_refs), so B3 labels will be weighted toward `search()` and `answer()` calls

**Decision: Proceed with B3 labeling after fixing trajectory capture and re-running on larger subset.**

The BM25 caching issue should be fixed first (adds ~10s per question × 45 items × multiple runs = significant total time).

---

## Recommended next steps (in order)

1. **Fix BM25 caching** in `ReActRAGAgent` — cache `BM25Retriever` across `search()` calls
2. **Re-run B1** on 20-item subset with fixed trajectory capture to generate label-ready JSONL
3. **Label trajectories** using `label_rubric.md` (target: ≥50 steps)
4. **B2 run**: use LLM judge to score each trajectory step (automatic)
5. **B3 run**: inject labeled trajectories as few-shot examples in agent system prompt
6. **B4 run**: compare SME-written tool descriptions (already in `react_agent.py`) vs LLM-generated
