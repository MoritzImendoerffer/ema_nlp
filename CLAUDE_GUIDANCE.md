# Guidance for Claude Code working on `ema_nlp`

This document explains the project intent, the developer's working style, and
the design rules that should hold across every change. Read this *before*
proposing implementation plans. Read `DECISIONS.md` for *why* current
choices were made and `ema_nlp_review.md` for *what* needs fixing.

---

## 1. Project intent (the real one)

The README says "tinkering with Graph RAG." That framing is misleading and
will be corrected. The actual project is:

**An evaluation toolkit for agentic RAG over EMA regulatory documents, with
human-in-the-loop review of both reasoning chains and final answers.**

Three goals in priority order:

1. **Compare RAG strategies honestly.** From simple RAG through CRAG and ReAct
   to composite workflows, measure where expert effort actually pays off.
   Quantitative answers backed by the 45-item T1–T4 benchmark.
2. **SME-in-the-loop for both step-level and answer-level review.** An SME
   should be able to walk through an agent's thought chain post-hoc, label
   individual steps (good / suboptimal / wrong, with reasons), and label the
   final answer. Eventually the agent learns from these labels.
3. **Eventually multi-hop reasoning across documents.** The corpus has
   `cross_refs` between Q&As; T3 benchmark questions require traversing them.

Out of scope for v1: graph databases, ontologies, biomedical literature
beyond regulatory Q&A, multilingual content. See `DECISIONS.md`.

---

## 2. The developer

- **Domain background:** bioprocess chromatography, pharma manufacturing,
  data science. Strong scientific Python. Newer to NLP / RAG specifics.
- **Time budget:** evenings only. ~6–9 weeks for v1. Cadence is small
  iterative deliverables, not large refactors in one go.
- **Environment:** Ubuntu home PC with Nvidia RTX 3090 (Vienna), HP
  EliteBook 845 G10 (Tyrol). Both run the project. State syncs through
  Nextcloud.
- **Preferences (encoded in chat settings, repeating here so they stick):**
  - **Ask before writing code.** Discuss design choices first.
  - **Start simple. Complexity arrives on its own.**
  - **Keep him in the loop.** No surprise scope expansion.
  - **No new features without asking.**
  - **Honest critical assessment over sycophancy.** Push back when wrong.
  - **Iterative deliverables.** Ship small, working pieces.

---

## 3. Working rules

### 3.1 Always ask before coding

When given a task, the first response is **a design discussion**, not code.
State:
- What you understand the goal to be (one or two sentences).
- The design decisions that need to be made before code is reasonable.
- Your recommendation for each, with the tradeoff explicit.
- What you'd touch (file paths, ~line counts) once the user approves.

Only after the user confirms do you write code.

If a task is genuinely tiny (one-line fix, obvious refactor), say so and
ask whether the design step is needed.

### 3.2 Read `DECISIONS.md` and `OPEN_QUESTIONS.md` before non-trivial work

These two files are the canonical record of *why* the project looks the way
it does. If a proposed change would contradict a decision in `DECISIONS.md`,
flag it explicitly and ask whether the decision should be revised. Don't
silently work around it.

After any decision-level change, **update `DECISIONS.md`** with the new
entry (date, what, why, references). Move resolved items out of
`OPEN_QUESTIONS.md` into `DECISIONS.md`.

### 3.3 Watch for duplication traps

The codebase has parallel paths from past iterations. Examples:

- `harness/answer_gen.py` and `harness/workflows/simple_rag.py` do the same
  thing through different APIs. **One should be deleted.**
- `harness/judge.py` reads its own LLM config. The reranker code constructs
  its own Anthropic client. The workflows use `harness/llms.py`. **All should
  go through `get_llm("<role>")`** (see review §5.5).
- The `Doc` dataclass exists to mimic LangChain's `Document` interface —
  LangChain is gone. **It should be deleted; use `TextNode`.**

When asked to "add a feature," check first whether the right move is to
**consolidate** an existing duplicate rather than create a third version.
If unsure, ask.

### 3.4 Separation of code and data

- **Code lives in the repo.** No large binaries, no traces, no labels, no
  results, no corpus, no index.
- **Data lives on Nextcloud** at `~/Nextcloud/Datasets/ema_nlp/`. This
  includes the corpus JSONL, the FAISS index, the query cache, the
  exported annotations, and (going forward) the eval results.
- **Phoenix** is the live trace and label store, backed by its own
  Postgres in a Docker volume on the home PC. Annotations are exported
  *from* Phoenix *to* Nextcloud JSONL for downstream use.

When adding any persistence:
- Code-shaped (small, versioned, deterministic) → repo.
- Data-shaped (large, generated, machine-specific, or user-input) → Nextcloud.

The existing `results/<run_id>/` directory in the repo predates this rule
and is scheduled to move. Don't add anything new under `results/` in the
repo.

### 3.5 The `harness/hitl/` package

A new package (created in week 3 of the roadmap) holds HITL code. Examples:
Phoenix annotation config setup, the `export_annotations.py` script, the
runtime interrupt event helpers. **Keep code separate from data**: this
package writes JSONL to Nextcloud, but the package itself is repo code.

### 3.6 Don't expand scope silently

If a task implies a feature that wasn't asked for (a new YAML key, a new
endpoint, a new dependency), **stop and ask**. The developer specifically
flagged "do not introduce new features without asking" — this includes
"helpful" additions like rate limiting, retry logic, fancy logging,
progress bars, etc.

Specifically *do not* introduce:
- New frameworks (LangChain, LangGraph, DSPy, etc.) — see §4 below.
- New observability tools (Datadog, OpenTelemetry exporters beyond Phoenix).
- New vector stores (Qdrant, Chroma, etc.) — FAISS is enough at 26k docs.
- New embedding models without a re-embed plan.
- New persistence layers (SQLite, additional Postgres).

### 3.7 Ship in small, working iterations

After every change set, the code should:
- Pass `pytest tests/`.
- Run `python -m harness.run_eval --config harness/configs/baseline_a0plus.yaml`
  successfully.
- Start `bash run_ui.sh` and answer a question.

If a change breaks any of the three, fix it in the same change set or
revert. Don't leave the tree broken between sessions — the developer might
not come back for a day or two.

---

## 4. Framework choices that are settled

These are decided. Don't propose changes without serious cause:

- **LlamaIndex Workflows for all orchestration.** Decided 2026-05-22. The
  LangChain + LangGraph bridge experiment failed because of metadata
  stripping. Don't bring them back.
- **FAISS flat-L2 as the vector store.** 26k docs; HNSW/IVF buys nothing.
- **BGE-large-en-v1.5 for embeddings.** Re-embedding is ~30 min on CPU; only
  switch if benchmark numbers actually justify it.
- **Phoenix + OpenInference for tracing.** Stays. Auto-instruments
  LlamaIndex. Phoenix annotation queues are the SME labelling UI; no custom
  trace explorer.
- **Chainlit for the chat UI.** Stays. Don't propose Streamlit, Gradio, or
  custom React.
- **Anthropic API (Claude Haiku / Opus) for now.** With the role/model split
  in week 2, the developer can swap any role to a local model on the 3090
  via Ollama / vLLM. The configuration must support that; the default
  models must not change without asking.
- **Eval design: stacked, not orthogonal grid.** Ablation A (retrieval)
  fixes the workflow at `simple_rag_zero`. A separate workflow comparison
  axis fixes retrieval at `A0+`. Don't propose a full N×M grid.

---

## 5. The roadmap (mirror of review §7)

If asked "what next," answer with the next item from this list. Don't skip
ahead without checking.

1. **Week 1:** Wire `run_eval.py` to `harness.workflows.registry`. Add
   `orchestration:` YAML block. Delete `harness/answer_gen.py`. Confirm
   baseline numbers reproduce.
2. **Week 2:** Fix the CRAG grader (per-doc + `missing_facts`). Refactor
   `models.yaml` into model definitions + role assignments. Add
   `openai_compatible` provider so the 3090 is a one-line config away.
3. **Week 3:** Native ReAct Workflow with per-step Phoenix spans
   (`harness/workflows/react_native.py`). Phoenix annotation configs for
   step_quality / tool_choice / arg_quality / answer_quality.
4. **Week 4:** `harness/hitl/export_annotations.py` to JSONL on Nextcloud.
   First SME labelling session over 5 questions × N strategies. Decide
   whether runtime interrupts are needed.
5. **Week 5:** Cleanup pass — BM25 caching, drop `Doc` dataclass, rerankers
   as `NodePostprocessor`, move EMA acronym hint to acronym dict, move
   `results/` to Nextcloud.
6. **Week 6:** Full ablation comparison run + write-up.

**v2:** Ablation B (process rewards), few-shot injection, DSPy at ≥50
rated trajectories, graph RAG *only* if `cross_refs` traversal proves
insufficient.

---

## 6. Sensitive files

Touch with extra care; ask before significant changes:

- **`corpus/corpus.jsonl`** — versioned, 26k records. Don't rebuild unless
  the developer asks; mention re-embed cost when relevant.
- **`benchmark/benchmark.jsonl`** — 45 items, hand-curated by an SME.
  Read-only from Claude Code's perspective unless explicitly asked.
- **`harness/configs/*.yaml`** — every config is a documented run. Changing
  the schema affects all of them. Migration must be coordinated.
- **`DECISIONS.md`** and **`OPEN_QUESTIONS.md`** — append-only spirit;
  don't rewrite history.
- **`~/.myenvs/ema_nlp.env`** — credentials. Never read, never write,
  never log.

Fair game (the working surface):

- `harness/workflows/`
- `harness/retrieve.py`
- `harness/run_eval.py`
- `harness/llms.py`, `harness/models.py`
- `harness/ablations/`
- `harness/hitl/` (new, week 3+)
- `app.py`
- `tests/`

---

## 7. Communication style

- Push back when the developer's plan looks wrong. He explicitly prefers
  honest assessment over sycophancy.
- Don't soften disagreement with excessive hedging ("perhaps we might
  consider possibly..."). State the case, give the reason, offer the
  alternative.
- When the developer is right, don't qualify it ("great question!" etc).
  Just engage.
- He has a biotech PhD and process-engineering background; analogies from
  bioprocessing, chromatography, statistics, and Bayesian methods land
  well. Don't dumb things down.
- Write English; the developer is fluent. German is fine for pleasantries
  but technical content should be English to match the codebase.

---

## 8. Quick reference

| Question | Answer |
| --- | --- |
| Should I write code now? | No — design first, unless trivial. |
| Should I add a new framework? | No. |
| Should I add a new file under `results/` in the repo? | No — Nextcloud. |
| Where do exported annotations go? | `~/Nextcloud/Datasets/ema_nlp/annotations/` |
| Where does Phoenix store traces? | Phoenix's own Postgres (Docker volume on home PC). |
| Which LLM does the agent use? | Whatever `roles.agent` resolves to in `models.yaml` (Claude Haiku by default in week 2+). |
| Which LLM does the grader use? | Whatever `roles.grader` resolves to (independent of agent). |
| Can I change a `DECISIONS.md` entry? | Add a new dated entry that supersedes it. Don't rewrite. |
| What's the next task? | See §5 — start at the lowest unchecked week. |
