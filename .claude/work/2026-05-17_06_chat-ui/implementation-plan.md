# Chat UI Implementation Plan

**Work unit:** `2026-05-17_06_chat-ui`  
**Created:** 2026-05-17  
**Status:** planning_complete

---

## Goal

Add a graphical chat interface to the EMA Q&A system as early as possible — inspired by Allen AI's OLMo demo + OLMo Trace — using open-source packages rather than custom-built UI code.

**User requirements:**
- Chat interface (not self-made)
- Source traces / provenance visible
- Chain of agent reasoning visible
- Per-step rating (feeds trajectory labeling for TASK-029)

---

## Technology decision: Chainlit + Arize Phoenix

After evaluating options (Gradio, Streamlit, LangSmith, Literal AI), the chosen stack is:

| Component | Package | Reason |
|-----------|---------|--------|
| Chat UI | **Chainlit 2.11** | Purpose-built for LLM apps; `cl.Step` for reasoning chains; `cl.SourceDocument` for provenance; `cl.Action` for per-step feedback |
| Trace visualization | **Arize Phoenix 15** | Already in deps; `localhost:6006` UI shows full LlamaIndex + Anthropic trace tree; `spans.add_span_annotation()` for human ratings |
| Auto-instrumentation | **openinference-instrumentation-llama-index** | Already in deps; auto-captures retrieval + embedding spans |
| LLM tracing | **openinference-instrumentation-anthropic** | New dep; auto-captures Claude API calls as LLM spans |

This gives the OLMo-like experience: Chainlit provides the chat + reasoning display (analogous to OLMo's chat demo), Phoenix provides the trace + source provenance viewer (analogous to OLMo Trace).

---

## Architecture

```
Browser
  │
  ▼
Chainlit (port 8000)              Phoenix UI (port 6006)
  │  app.py                          │
  │  ├── on_message()                │  Trace tree:
  │  │   ├── cl.Step: Retrieval ──────────► LlamaIndex.retrieve span
  │  │   │   ├── [👍][👎] buttons           ├── embed span
  │  │   │   └── cl.SourceDocument ×k       └── FAISS span
  │  │   ├── cl.Step: Generation ────────► Anthropic.messages span
  │  │   │   └── [👍][👎] buttons           ├── prompt tokens
  │  │   └── cl.Message: answer             └── completion tokens
  │  │       └── "View trace →" link
  │  │
  │  └── on_action()
  │      └── Phoenix client: spans.add_span_annotation()
  │                          ▲
  └──────────────────────────┘  (span_id from OpenInference context)
```

---

## Tasks

### TASK-UI-001 · Chainlit RAG chat (no MongoDB) · 3h

**File:** `app.py` (repo root)

Core logic:
```python
@cl.on_chat_start
async def start():
    # Load index once per session (mini_corpus or full corpus)
    index = load_index(DEFAULT_INDEX_DIR)
    cl.user_session.set("index", index)

@cl.on_message
async def main(message: cl.Message):
    index = cl.user_session.get("index")

    async with cl.Step(name="Retrieval", type="retrieval") as step:
        results = retrieve(index, message.content, mode="hybrid", k=10)
        step.output = f"Found {len(results)} documents"
        # Show sources
        elements = [cl.SourceDocument(...) for qa_id, score, meta in results[:5]]

    async with cl.Step(name="Synthesis", type="llm") as step:
        # Call Claude to synthesise answer from retrieved context
        answer = await generate(message.content, results)
        step.output = "Done"

    await cl.Message(content=answer, elements=elements).send()
```

**Start command:** `chainlit run app.py --port 8000`

### TASK-UI-002 · Phoenix trace integration · 2h

Wire instrumentation at `app.py` import time:
```python
from openinference.instrumentation.llama_index import LlamaIndexInstrumentor
from openinference.instrumentation.anthropic import AnthropicInstrumentor
from phoenix.otel import register

tracer_provider = register(project_name="ema-nlp")
LlamaIndexInstrumentor().instrument(tracer_provider=tracer_provider)
AnthropicInstrumentor().instrument(tracer_provider=tracer_provider)
```

Add trace link to each response:
```python
span_id = get_current_span().get_span_context().span_id
trace_url = f"http://localhost:6006/projects/ema-nlp/traces/{format_trace_id(trace_id)}"
await cl.Message(content=answer, elements=[cl.Text(content=f"[View trace]({trace_url})")]).send()
```

### TASK-UI-003 · Per-step rating → Phoenix annotations · 3h

```python
# Attach rating buttons to each step
actions = [
    cl.Action(name="rate_step", payload={"span_id": span_id, "label": "good"},  value="good",  label="👍"),
    cl.Action(name="rate_step", payload={"span_id": span_id, "label": "bad"},   value="bad",   label="👎"),
]
step.elements = [cl.Text(content="Rate this step:"), *actions]  # or via step.actions

@cl.action_callback("rate_step")
async def on_rate(action: cl.Action):
    span_id = action.payload["span_id"]
    label   = action.payload["label"]
    score   = 1 if label == "good" else -1
    px_client.spans.add_span_annotation(
        span_id=span_id, name="human_feedback", label=label, score=score
    )
    await cl.Message(content=f"Recorded: {label}").send()
```

### TASK-UI-004 · Agent integration (deferred until TASK-027) · 2h

Add `--mode agent` flag. In agent mode, each `tool_call` event from the ReAct agent maps to a `cl.Step` with a rating button. The agent streams intermediate steps live as the ReAct loop runs.

---

## What this enables early

| Capability | Available after |
|-----------|----------------|
| Chat with EMA Q&As | TASK-UI-001 (now, mini-corpus) |
| See retrieved sources in UI | TASK-UI-001 |
| Phoenix trace view (retrieval + LLM tree) | TASK-UI-002 |
| Rate individual retrieval / synthesis steps | TASK-UI-003 |
| Full agent reasoning chain in UI | TASK-UI-004 + TASK-027 |

---

## Relation to existing plan (main state.json)

- **TASK-027.8** (CLI rating UI + Phoenix annotation) is superseded by TASK-UI-003. The Chainlit UI provides a better interface than a CLI prompt. Mark TASK-027.8 as `superseded` in main state.json once TASK-UI-003 is complete.
- **TASK-027.7** (runtime few-shot injection) still applies but reads from Phoenix annotations created by TASK-UI-003 instead of a separate CLI flow.
- **TASK-029** (SME trajectory labeling) is facilitated by TASK-UI-003: SME rates steps in the chat UI → annotations stored in Phoenix → exported for training.

---

## Dependencies to add

```toml
# pyproject.toml [project.optional-dependencies] — new 'ui' group
ui = [
    "chainlit>=2.11",
    "openinference-instrumentation-anthropic>=0.1",
]
```

`arize-phoenix` and `openinference-instrumentation-llama-index` are already in `[project.dependencies]`.

---

## Running the stack

```bash
# Terminal 1 — Phoenix observability server
python3 -m phoenix.server.main serve

# Terminal 2 — Chainlit chat UI
chainlit run app.py --port 8000

# Browser
# Chat:   http://localhost:8000
# Traces: http://localhost:6006
```
