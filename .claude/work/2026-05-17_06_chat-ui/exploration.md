# Exploration: Chat UI with Trace Provenance

**Work unit:** `2026-05-17_06_chat-ui`
**Date:** 2026-05-17

---

## What is already in the roadmap

The roadmap (Phase 4B) planned a **CLI-only** rating UI (TASK-027.8: "CLI rating UI + Phoenix annotation posting"). No web or chat UI was planned.

The user's requirement — an OLMo-style browser chat interface with source provenance and CoT visibility — is new scope relative to the roadmap. It supersedes TASK-027.8.

---

## Reference: Allen AI OLMo interface

The OLMo playground (allenai.org/olmo) provides:
1. **Chat panel** — streaming question/answer
2. **Sources panel** — retrieved documents with highlighted passages
3. **OLMo Trace** (separate tool) — span tree showing retrieval and generation steps

This project replicates this split using:
- **Chainlit** → chat panel + step display (analogous to OLMo chat)
- **Arize Phoenix** → trace viewer (analogous to OLMo Trace) — already a project dependency

---

## Technology choice: Chainlit 2.11

Evaluated options:

| Option | Verdict |
|--------|---------|
| **Gradio** | Good for demos; `gr.Chatbot` + custom components for sources. But no native reasoning-step concept — would need custom HTML. |
| **Streamlit** | Flexible layout but no streaming without `st.write_stream`; CoT display requires manual state management. |
| **Chainlit** ✓ | Purpose-built for LLM chat apps. `cl.Step` = native reasoning chain concept. `cl.SourceDocument` = native provenance. `cl.Action` = native feedback buttons. Streaming built-in. Best fit. |
| **LangSmith / Literal AI** | Managed services with auth/billing. Out of scope for local-first project. |

**Chosen: Chainlit 2.11** — the only library that natively models "reasoning steps + source documents + feedback" without custom UI code.

---

## What's already built that app.py wires together

| Component | Location | Status |
|-----------|----------|--------|
| Hybrid retriever (dense + BM25 + RRF) | `harness/retrieve.py` | ✅ complete |
| LlamaIndex VectorStoreIndex + FAISS | `harness/embed.py` | ✅ complete |
| Claude LLM integration | via `llama-index-llms-anthropic` | ✅ in deps |
| Phoenix tracing (LlamaIndex spans) | `openinference-instrumentation-llama-index` | ✅ in deps |
| Corpus Q&A records | `corpus/mini_corpus.jsonl` (small), `corpus/corpus.jsonl` (full) | ✅ exist |

**app.py is glue code only** — no new business logic, just wiring.

---

## Architecture

```
Browser (Chainlit — localhost:8000)        Phoenix UI (localhost:6006)
  │                                           │
  ▼                                           │  Trace tree per query:
[Query input]                                 │  ├── LlamaIndex.retrieve
  │                                           │  │   ├── embed span
  ▼                                           │  │   └── FAISS span
cl.Step("Retrieval")  ────────────────────────►  └── Anthropic.messages
  ├── harness/retrieve.py (hybrid k=10)       │      ├── prompt tokens
  ├── output: "Found N docs, top score 0.87"  │      └── completion tokens
  ├── cl.SourceDocument ×5                    │
  └── [👍][👎] → Phoenix span annotation      │
  │                                           │
cl.Step("Synthesis")  ────────────────────────►
  ├── Claude API call (streaming)             │
  ├── output: "Done (342 tokens)"             │
  └── [👍][👎] → Phoenix span annotation      │
  │
cl.Message(answer)
  └── "View trace →" http://localhost:6006/...
```

---

## Index loading strategy

`app.py` needs to load the LlamaIndex VectorStoreIndex at startup. Two modes:

1. **Mini-corpus (default, no API key needed for indexing)** — loads from `harness/index/` if the directory exists and contains a persisted index. If not, builds from `corpus/mini_corpus.jsonl` using the BGE embedding model.
2. **Full corpus** — `EMA_INDEX_PATH=/path/to/index chainlit run app.py`. Points at a pre-built index over the full 26k corpus.

Building the full index requires `ANTHROPIC_API_KEY` (for Claude synthesis) but not for indexing (BGE is local).

---

## Phoenix integration details

- **Instrumentation** wired at `app.py` import time via `phoenix.otel.register()` + `LlamaIndexInstrumentor` + `AnthropicInstrumentor`
- **Span ID capture**: `opentelemetry.trace.get_current_span().get_span_context()` inside each `cl.Step` block
- **Annotation API**: `phoenix.Client().spans.add_span_annotation(span_id, name, label, score)`
- **Trace URL format**: `http://localhost:6006/projects/ema-nlp/traces/{trace_id}`
- **Fallback**: if Phoenix is not running or `PHOENIX_DISABLED=1`, all annotation calls are no-ops

---

## Relation to existing plan tasks

| Existing task | Status after this work unit |
|---------------|---------------------------|
| TASK-027.8 (CLI rating UI) | Superseded by TASK-UI-003 |
| TASK-027.7 (runtime few-shot injection) | Still applies; reads Phoenix annotations created by TASK-UI-003 |
| TASK-029 (SME trajectory labeling) | Uses TASK-UI-003 annotations as input |
| TASK-027 (ReActAgent) | Still needed for TASK-UI-004 (agent mode) |

---

## New dependencies

```toml
[project.optional-dependencies]
ui = [
    "chainlit>=2.11,<3",
    "openinference-instrumentation-anthropic>=0.1",
]
```

Install with: `pip install -e ".[ui]"`
