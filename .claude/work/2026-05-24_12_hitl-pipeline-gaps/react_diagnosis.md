# React workflow diagnosis — HITL-004a findings

Date: 2026-05-24  
Setup: 8-question sample (2 per type), claude_opus as agent role, same hybrid k=10 retrieval.

---

## Score comparison

| bench_id | type | Opus correct | Haiku correct (from REFACT-022) |
|----------|------|-------------|--------------------------------|
| T1-001   | T1   | 5/5          | ~2-3/5 (estimated)            |
| T1-002   | T1   | 2/5          | ~2/5                           |
| T2-001   | T2   | 4/5          | ~1-2/5                         |
| T2-002   | T2   | 1/5          | ~1/5                           |
| T3-001   | T3   | 2/5          | ~1/5                           |
| T3-002   | T3   | 1/5          | ~1/5                           |
| T4-001   | T4   | 1/5          | 1/5                            |
| T4-002   | T4   | 1/5          | 1/5                            |

**Opus average correctness: 2.13/5** (vs Haiku 1.82/5 on 31-question run — marginal improvement).

---

## Critical finding: trajectory=0 for ALL 8 questions with Opus

Every question showed `trajectory steps = 0`. No `ema_search` or other tool calls were made on ANY question. This rules out H3 (tool result truncation).

**Both Haiku and Opus skip the tool-calling loop entirely** — confirming H2 (prompt allows direct Final Answer).

---

## Two distinct root causes

### Bug 1: System prompt does not prevent skipping tool calls (H2 confirmed)

The `_SYSTEM_PROMPT` in `react_native.py` instructs "Always call ema_search before answering" but does not prohibit going straight to `Final Answer:`. Both models treat the first LLM call as an opportunity to answer from memory rather than calling tools.

Evidence: T1-001 with Opus scores 5/5 purely from training knowledge (correct answer, no retrieval). The RAG pipeline is effectively bypassed.

Fix: Add a hard constraint in the system prompt. The most reliable technique is to **prefill the assistant turn** with "Thought:" on iteration 0, forcing the model into the format. Alternatively, add an explicit prohibition: "DO NOT write Final Answer until ema_search has been called."

### Bug 2: _parse_thought only captures first line of Final Answer (truncation bug)

`_parse_thought` in `react_native.py` extracts Final Answer content only from the same line as "Final Answer:":

```python
elif stripped.startswith("Final Answer:"):
    final_answer = stripped[len("Final Answer:"):].strip()  # single line only
```

If the model outputs:
```
Final Answer: The fee arrangements differ significantly:
- Article 30: fees always levied…
- Article 31: fees when MAH initiated…
```

The captured answer is only "The fee arrangements differ significantly:" — the bullet list is discarded.

Evidence: T4-001 answer = "The fee arrangements for Article 30 and Article 31 pharmacovigilance referrals differ significantly:" (judge scores 1/5 for being empty).

Fix: Capture everything after the "Final Answer:" line to end of response.

### H1 (model capacity) — partially confirmed, not the primary issue

Opus shows better T1/T2 scores (5/5, 4/5) vs Haiku because Opus has more regulatory training knowledge. But BOTH models skip tool calls. H1 is a secondary effect: Haiku fails because it lacks EMA knowledge AND skips retrieval. Opus succeeds on T1/T2 because it has EMA knowledge even without retrieval.

**Implication:** Even if we fix the prompt to force tool calls, Haiku may still produce poor answers for T2/T3/T4 (less domain knowledge). The permanent agent role for react should be `claude_opus` or `claude_sonnet`.

---

## Recommended fixes for HITL-004b

1. **`_parse_thought` bug fix** — capture everything from "Final Answer:" to end of raw string, not just the current line. Quick, unambiguous, high-value fix.

2. **System prompt hard constraint** — add explicit prohibition: "REQUIREMENT: You MUST call ema_search at least once before writing 'Final Answer:'. Do not write 'Final Answer:' on your first response." Additionally, on iteration 0 (empty history), prepend a partial assistant message "Thought:" to force the structured format.

3. **Permanently set agent role to claude_opus** in models.yaml — even with fixed prompts, Opus is more reliable for complex EMA regulatory Q&A. Haiku can remain as grader/rewriter where cost matters more.

4. **Increase Opus max_tokens to 4096** in models.yaml — T4 synthesis answers can be multi-paragraph. 2048 is likely insufficient for Opus's verbose style.
