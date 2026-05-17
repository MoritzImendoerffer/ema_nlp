# Requirements: Chat UI with Trace Provenance

**Work unit:** `2026-05-17_06_chat-ui`
**Inspiration:** Allen AI OLMo playground + OLMo Trace

---

## Functional requirements

### FR-1 · Chat interface
- Browser-based chat input/output (not CLI)
- User submits a natural-language question; system streams back an answer
- Works immediately with `mini_corpus.jsonl`; no MongoDB required for initial use
- Full `corpus.jsonl` loadable via env var or flag

### FR-2 · Source provenance ("Referenced documents and chunks")
- Each answer shows the retrieved Q&A records used to generate it
- Per-source card displays: question text, topic_path, source_url, relevance score
- Clickable links to EMA source documents

### FR-3 · Chain-of-thought traceability
- Reasoning steps shown in the UI as the system processes the query:
  1. **Retrieval step**: how many docs found, hybrid vs dense mode, top scores
  2. **Synthesis step**: prompt construction, Claude API call
- Each step collapsible; shows timing
- "View trace →" link opens the full Phoenix span tree (embedding, FAISS, LLM token counts)

### FR-4 · Per-step feedback rating
- Each reasoning step (retrieval / synthesis) has 👍/👎 buttons
- Clicking records a Phoenix span annotation (label + score)
- Feeds TASK-029 trajectory labeling for Ablation B

### FR-5 · Agent mode (deferred — requires TASK-027)
- `--mode agent` flag activates the ReAct agent
- Each tool call (retrieve, follow_cross_refs, filter_by_concept) appears as a step
- Steps stream live as the agent loop runs
- Per-step rating buttons on each tool call

---

## Non-functional requirements

- **No new runtime deps beyond pyproject.toml `[ui]` extras** — `chainlit>=2.11`, `openinference-instrumentation-anthropic>=0.1`
- **Phoenix optional** — if `PHOENIX_DISABLED=1`, tracing silently disabled; app still works
- **Single-file app** — `app.py` at repo root, ≤ 250 lines, no separate server process required for the chat UI itself
- **Startup time** — index load ≤ 30s on cold start; cached after that
- **Ruff + mypy clean**

---

## Acceptance criteria summary

| Task | Key acceptance criterion |
|------|--------------------------|
| TASK-UI-001 | `chainlit run app.py` starts; chat answers with source cards visible |
| TASK-UI-002 | Phoenix `localhost:6006` shows retrieval + LLM spans for each query |
| TASK-UI-003 | 👍/👎 buttons on steps; annotations appear in Phoenix |
| TASK-UI-004 | `--mode agent` streams each ReAct tool call as a step (after TASK-027) |

---

## Risks

| Risk | Mitigation |
|------|-----------|
| Chainlit API changes between 2.x versions | Pin to `chainlit>=2.11,<3` |
| Phoenix span_id retrieval API varies by instrumentation version | Test against installed versions; fall back to no trace link if unavailable |
| `mini_corpus.jsonl` too small for interesting queries | Use `EMA_INDEX_PATH` env var to point at full `corpus.jsonl`-built index |
| TASK-UI-004 blocked indefinitely by TASK-027 | First three tasks fully independent and shippable |
