# `ema_nlp` review — current state, issues, recommendations (v2)

**Reviewed:** 2026-05-22
**Commit:** `main` (HEAD at clone time)
**Scope:** retrieval pipeline, orchestration layer, HITL/feedback, framework choice.
**v2 changes:** incorporates design decisions from the 2026-05-22 conversation.
A separate `CLAUDE_GUIDANCE.md` is provided for Claude Code.

---

## 1. Executive summary

You have a solid, well-instrumented retrieval foundation and a clean, recent
decision (2026-05-22) to consolidate everything on **LlamaIndex Workflows**.
That decision is sound and the code confirms it.

The biggest risks are not the framework choice — they are:

1. **A path split in the benchmark harness.** `harness/run_eval.py` does not use
   `harness/workflows/`. It has its own retrieval + answer-generation path
   (`harness/answer_gen.py`). So your nine registered workflows (CRAG, ReAct,
   composites) are **only reachable through the Chainlit UI**. You cannot
   measure them on the benchmark today.
2. **The HITL story is shallower than the docs imply.** A 👍/👎 button hitting
   a "most recent root span" heuristic is not really per-step
   human-in-the-loop. Phoenix has the right primitives (span-level annotation
   queues, configurable label schemas); the code just doesn't use them.
3. **The CRAG grader is naïve and ungrounded.** A single-word
   `"sufficient" / "insufficient"` LLM judgement is essentially a yes-biased
   coin flip. This is the biggest *retrieval-quality* logic problem in the code.
4. **LLM role and tier are conflated.** `tier_id` (`"mid"|"frontier"|"olmo"`)
   determines both *which model* and *which role*. To swap "the grader" to a
   local model on your 3090 while keeping the agent on Claude, you'd have to
   change the agent's model too. Needs a role/model separation.

Recommendations in §5–7. The framework discussion in §6 is unchanged but
shorter — the answer is "stay with LlamaIndex Workflows."

---

## 2. Architecture recap

```
corpus.jsonl  (26k Q&A)
    │
    └─► harness/embed.py ──► FAISS flat-L2 + LlamaIndex docstore + cross_refs metadata
                              │
                              ▼
                  harness/retrieve.py   (dense | bm25 | hybrid-RRF)
                  RetrievalConfig       (flat | recursive | hierarchical | agentic)
                              │
            ┌─────────────────┴─────────────────┐
            │                                   │
   harness/run_eval.py                  harness/workflows/    (9 strategies)
   (own retrieve_fn + answer_gen.py)    registry → simple_rag, crag, react,
                                        summarize_rag, composites, review
                                        │
                                        └─► app.py  (Chainlit UI)
                                               │
                                               └─► Phoenix (OpenInference traces)
```

Two parallel pipelines. The eval harness and the UI share retrieval and
prompts but **not orchestration**. Root cause of several issues below.

---

## 3. What's good (keep these)

- **Corpus and benchmark.** 26k Q&A records, 45 evaluation items stratified
  across T1–T4 with numeric-threshold contamination resistance. Excellent
  design — the kind of asset many "RAG benchmark" repos lack.
- **Stable `qa_id` hashing.** `sha256(url + question)[:16]`. Survives re-runs.
- **FAISS flat-L2 is the right default at 26k.** Don't move to HNSW/IVF until
  there's a latency problem.
- **RRF hybrid is implemented correctly.** Standard `K=60`, no LLM, rank-based.
- **`excluded_embed_metadata_keys`** is set so only Q+A text is embedded.
- **Phoenix + OpenInference at framework level.** Auto-traces every retrieval,
  every LLM call, every workflow step. Model-agnostic. Self-hosted. Free.
- **Stack consolidation (2026-05-22).** Killing the LangChain bridge was the
  correct call. The `EMARetriever` adapter that stripped node metadata was a
  real bug source.
- **`extract_answer` for CoT** (`<reasoning>…</reasoning>` strip) is robust.
- **DECISIONS.md / OPEN_QUESTIONS.md discipline.** Rare to see in a side
  project. Keep it.
- **LLM factory pattern already exists.** `harness/llms.py` reads
  `models.yaml` and dispatches on `provider:`. Easy to extend.

---

## 4. Issues, ranked

### 4.1 Critical — benchmark cannot measure agentic strategies

`harness/run_eval.py` does not import `harness.workflows.registry` anywhere.
The eval pipeline:

1. Builds its own `retrieve_fn` from `make_raw_retriever` + ablation A wrappers.
2. For Ablation C, calls `harness.answer_gen.generate_answer` directly, which
   is a near-duplicate of `SimpleRAGWorkflow.retrieve_and_generate`.

So when you ask "does CRAG/ReAct/CRAG-review help on T3 multi-hop?", **you
cannot answer that with the current eval script.** You can only see them in
the Chainlit UI one query at a time.

Highest-leverage thing to fix. See §5.1.

### 4.2 Critical — no usable HITL surface for step-level review

Despite the stated goal ("control and guide the agent, correct it if it
wanders"), the current HITL surface is:

- One 👍/👎 button **after** the full pipeline has finished.
- A CLI rating prompt in `harness/rating.py` that also runs **after** the answer.
- Optional per-step labels in `rating.py`, but they're CLI prompts attached
  to a fragile "most recent root span" heuristic.

You can't:

- Walk through past traces and label individual reasoning steps via UI.
- Filter spans by label (e.g. "show all `wrong_step` retrieval decisions").
- Export labels for downstream use (few-shot injection, DSPy).

**Phoenix already provides all of this** through annotation queues and
configurable label schemas — the code just doesn't define schemas or use
queues. See §5.3.

### 4.3 High — duplicated answer-generation path

`harness/answer_gen.py` (`generate_answer`) and
`harness/workflows/simple_rag.py` (`SimpleRAGWorkflow.retrieve_and_generate`)
do the same thing through different APIs. When you change a prompt, you may
need to think about which path picks it up. Tracing looks different in the
two paths (LlamaIndex auto-instrumented vs raw SDK).

**Fix:** delete `answer_gen.py`, have `run_eval.py` route through workflows.

### 4.4 High — CRAG grader is too crude to trust

`harness/workflows/crag.py`, `_GRADE_SYSTEM`:

```
"Respond with exactly one word: 'sufficient' or 'insufficient'. Do not explain."
```

```python
is_sufficient = "sufficient" in raw and "insufficient" not in raw
```

Problems:

1. **LLM yes-bias.** Single-token judgements on 10 plausibly-relevant passages
   almost always say "sufficient". Rewrite loop rarely triggers.
2. **No per-document grading.** Original CRAG grades each document
   individually. Your version is binary and global.
3. **No grounding.** The grader sees passages but isn't asked to identify the
   *information gap*.
4. **Silent quality degradation.** "Max cycles reached, generating anyway"
   should log the full trail.

Fix in §5.2.

### 4.5 High — LLM role/tier conflation

Currently `tier_id` is both *which model* and *what role*. Examples:

- Agent calls go through `get_llm("mid")` → Haiku.
- Grader calls in CRAG also use `self._llm` → same Haiku.
- Reranker in `a3_reranker.py` hardcodes Anthropic SDK directly.
- Judge in `harness/judge.py` reads its own model config.

To use your 3090 for the grader while keeping Claude for the agent, you'd
need to edit code, not config. The 3090 lets you host Qwen 2.5 32B or
Llama 3.1 70B Q4 via Ollama and serve OpenAI-compatible — but the codebase
can't currently target that selectively.

Fix in §5.5.

### 4.6 High — ReAct system prompt has a hardcoded domain hint

`harness/workflows/react.py`:

```python
"IMPORTANT: 'AI' means Acceptable Intake (ng/day), not Artificial Intelligence, "
"in EMA Q&A documents."
```

A band-aid for acronym ambiguity glued into one strategy's system prompt.
The acronym dictionary exists at
`ablations/A_evidence_filter/acronym_dict.yaml`. Move the knowledge there;
ReAct should call query expansion like everything else.

### 4.7 Medium — BM25 rebuilt on every call

`make_bm25_retriever` retokenises 26k docs (~0.5 s) every invocation. Trivial
to fix: cache per session.

### 4.8 Medium — A2 "concept" retriever silently falls back

If `tag_concepts.py` wasn't run first, `make_concept_retriever` matches
nothing and silently degrades to dense retrieval. Run completes; results
look identical to baseline; nothing logs the discrepancy. Fail loudly or
warn prominently in `run_summary.md`.

### 4.9 Medium — `cited_qa_ids` empty for most ReAct runs

`_ReactRunner` only appends to `cited_qa_ids` when `get_qa_by_id` is called.
The agent rarely calls it (it answers from `ema_search` output directly). So
citation-accuracy metrics on ReAct read ~0 even when grounded. Either parse
citations out of the answer text or require structured citations from the
agent.

### 4.10 Low — three document representations

`Doc` dataclass, LlamaIndex `TextNode`, and dict-shaped corpus entries all
pass through different parts of the code. Each transition costs metadata
fidelity. `Doc` was created to mimic LangChain's `Document` — LangChain is
gone now, `Doc` is dead weight.

### 4.11 Low — Phoenix span lookup heuristic

`_find_recent_root_span_id` returns "most recent root span in last 5
minutes." Wrong for concurrent users; OK for solo use today.

### 4.12 Documentation drift (mostly resolved)

README and ARCHITECTURE.md correctly reflect LlamaIndex Workflows.
RETRIEVAL_PIPELINE.md still says A3/A4 rerankers use "Anthropic SDK
directly" — true today, but inconsistent with the workflow LLM consolidation.
Rerankers should go through `get_llm()` after §5.5.

### 4.13 README framing

The README still says "Tinkering with Graph RAG" — but the project is
agentic RAG, with `cross_refs` as metadata edges (not a property graph or
Neo4j). DECISIONS.md correctly defers graph RAG to v2+. Fix the framing.

---

## 5. Recommendations

### 5.1 (P0) Wire `run_eval.py` to the workflow registry

Add an **orchestration block** to the eval YAML configs:

```yaml
orchestration:
  strategy: simple_rag_zero    # any key in WORKFLOW_REGISTRY
  # strategy-specific knobs go here, e.g.:
  # crag:
  #   max_cycles: 2
  #   review_threshold: 0.6
```

Existing configs need ~2 lines added (default `strategy: simple_rag_zero`
reproduces current baseline behaviour).

In `run_eval.py`, replace the inline `generate_answer` call with:

```python
from harness.workflows.registry import get_workflow
runner = get_workflow(cfg["orchestration"]["strategy"],
                      index=index, llm=llm,
                      retrieval_config=ret_config,
                      **cfg["orchestration"].get(cfg["orchestration"]["strategy"], {}))
result = runner.invoke({"question": item["question"]})
```

Delete `harness/answer_gen.py` after migrating callers.

**Eval design (stacked, per your decision):**
- Ablation A (retrieval variants A0/A0+/A1–A5) stays fixed on
  `simple_rag_zero`. This isolates retrieval improvements.
- A separate workflow comparison axis runs each registered strategy (`crag`,
  `react`, `crag_review`, `react_review`) on a fixed strong retrieval
  baseline (`A0+` hybrid). This isolates orchestration improvements.

This avoids the N×M grid you said you didn't want.

### 5.2 (P0) Fix the CRAG grader

Two independent improvements:

**(a) Per-document grading with reasoning.** Replace the one-word grade:

```text
For each retrieved document, rate its relevance to the question on 0–2:
  0 = irrelevant
  1 = related but doesn't directly answer
  2 = directly answers a required part of the question

List any specific factual claims the question requires that are NOT
supported by any of the documents.

Return JSON:
{
  "per_doc": [{"qa_id": "...", "score": 0|1|2, "covers": "..."}],
  "missing_facts": ["..."]
}
```

Trigger rewrite if either (i) zero docs scored 2, or (ii) `missing_facts` is
non-empty. Per-doc scores become spans the SME can review.

**(b) Better rewrite prompt:** pass `missing_facts` back in so the rewrite
*targets* the gap instead of guessing.

You said breaking comparability with existing CRAG results is fine, so just
change it.

### 5.3 (P0) Use Phoenix's annotation queues for SME review

You don't need to build a trace explorer. Phoenix has the right primitives.
Configure them properly:

1. **Define annotation configs in Phoenix** (a Phoenix UI / API setup step,
   no Python code required). Suggested vocabulary:
   - `step_quality`: categorical {`good`, `suboptimal`, `wrong`}.
   - `tool_choice`: categorical {`correct_tool`, `wrong_tool`, `unnecessary`}.
   - `arg_quality`: categorical {`correct_args`, `narrow`, `broad`, `wrong_args`}.
   - `result_interpretation`: categorical {`correct`, `partial`, `missed`}.
   - `answer_quality`: 1–5 scale + freeform reason.
   - `failure_mode`: categorical taxonomy from AgentHallu
     (`planning`, `retrieval`, `reasoning`, `tool_use`, `none`) plus freeform.

   Each label config gets attached to the right span type (e.g. tool-call
   spans get `tool_choice`, root spans get `answer_quality`).

2. **Annotation queues per workflow strategy.** Phoenix supports filtering
   spans into queues; create a queue for "recent CRAG runs awaiting SME
   review" so you have a one-click "next trace to label" flow.

3. **Per-step span granularity for ReAct.** Phoenix already captures
   `FunctionAgent` tool spans via OpenInference auto-instrumentation, but
   the granularity will improve once you replace `FunctionAgent` with a
   native ReAct Workflow (§5.4).

4. **Export to JSONL for downstream use.** Write
   `harness/export_annotations.py` that pulls labelled spans from Phoenix's
   API and writes them to Nextcloud as JSONL:
   ```
   ~/Nextcloud/Datasets/ema_nlp/annotations/YYYY-MM-DD.jsonl
   ```
   Schema:
   ```json
   {"trace_id": "...", "span_id": "...", "span_name": "tool_call.ema_search",
    "input": {...}, "output": {...},
    "labels": {"step_quality": "wrong", "tool_choice": "wrong_tool"},
    "reason": "...", "annotated_by": "moritz", "annotated_at": "..."}
   ```
   This is the artifact downstream tools consume (few-shot injection, DSPy,
   manual analysis). Phoenix stays the source of truth for traces; Nextcloud
   stays the source of truth for *exported* labels.

**Where things live:**

| Artifact          | Storage                                       |
| ----------------- | --------------------------------------------- |
| Spans (raw)       | Phoenix Postgres (Docker volume)              |
| Labels (live)     | Phoenix Postgres (attached to spans)          |
| Labels (exported) | `~/Nextcloud/Datasets/ema_nlp/annotations/`   |
| Cache             | `~/Nextcloud/Datasets/ema_nlp/index/` (existing) |
| Corpus / index    | `~/Nextcloud/Datasets/ema_nlp/` (existing)    |
| Reports / results | `~/Nextcloud/Datasets/ema_nlp/results/` (move from repo) |
| Code              | Repo (no large binaries, no labels, no traces) |

The principle: anything generated by running the system goes to Nextcloud;
code goes to git. The current `results/` directory in the repo violates this
and should move to Nextcloud with a symlink for convenience.

### 5.4 (P1) Build a native ReAct Workflow with per-step spans

`_ReactRunner` wraps `FunctionAgent` + `AgentWorkflow`. OpenInference does
auto-instrument these, so you get *some* spans today — but the structure is
opaque (one big agent span with tool subspans, not the
thought→action→observation triplet structure you'd want to label).

Build `harness/workflows/react_native.py` as a hand-written ReAct Workflow:

```text
StartEvent → think → ThoughtEvent
ThoughtEvent → act → ActionEvent (or FinishEvent)
ActionEvent → observe → ObservationEvent
ObservationEvent → think (loop)
FinishEvent → StopEvent
```

Each step is its own Phoenix span, annotatable independently. Solves §4.2
(per-step labelling), §4.9 (citations can be parsed from `FinishEvent`).

Keep the existing `react` workflow as `react_legacy` so existing eval runs
still work.

### 5.5 (P1) Separate LLM roles from model tiers

Refactor `models.yaml` into two sections:

```yaml
# Section 1: model definitions (the "what")
models:
  claude_haiku:
    provider: anthropic
    model_id: claude-haiku-4-5-20251001
    max_tokens: 1024
    temperature: 0.0

  claude_opus:
    provider: anthropic
    model_id: claude-opus-4-7
    max_tokens: 2048
    temperature: 0.0

  olmo_32b:
    provider: openai_compatible      # new generic provider
    api_base: https://api.together.xyz/v1
    api_key_env: TOGETHER_API_KEY
    model_id: allenai/OLMo-2-1124-32B-Instruct
    max_tokens: 2048

  local_qwen32:                       # for your 3090 box via Ollama
    provider: openai_compatible
    api_base: http://localhost:11434/v1
    api_key_env: OLLAMA_API_KEY       # Ollama ignores it but the field is uniform
    model_id: qwen2.5:32b-instruct-q4_K_M
    max_tokens: 2048

# Section 2: role assignments (the "where")
roles:
  agent:      claude_haiku       # the model running CRAG / ReAct / SimpleRAG
  grader:     claude_haiku       # CRAG sufficiency / per-doc grading
  rewriter:   claude_haiku       # CRAG query rewrite
  reranker:   claude_haiku       # A3/A4 LLM rerankers
  judge:      claude_opus        # eval-time faithfulness / correctness
  reviewer:   claude_opus        # workflow-time faithfulness review
```

API change: `get_llm("agent")`, `get_llm("grader")` etc. — by *role*, not tier.
Each ablation config can override the assignment:

```yaml
orchestration:
  strategy: crag
  role_overrides:
    grader: local_qwen32          # try local grader for this run
```

Implementation:
- Add a generic `openai_compatible` provider in `harness/llms.py` (Ollama,
  vLLM, LM Studio, OpenRouter all speak this).
- Migrate `harness/judge.py` and the A3/A4 rerankers to use `get_llm("judge")`
  / `get_llm("reranker")` instead of constructing their own SDK clients.
- Keep `tier_id` as a backward-compat alias for now; deprecate later.

Net effect: one-line config change swaps the grader between Claude and local
Qwen without touching code or breaking the agent's model.

### 5.6 (P1) Add a HITL interrupt — minimum useful version

Now that per-step spans exist (§5.4) and Phoenix annotation queues are set
up (§5.3), the *runtime* HITL piece becomes smaller. One feature is enough
to test the design:

**"Confirm sufficient before generating."** In `CRAGReviewWorkflow`, after
the grade step decides `sufficient`, emit a `HumanConfirmEvent` and use
`ctx.wait_for_event(...)` to pause until the SME (in Chainlit) confirms or
overrides. Default to auto-confirm after 10 s so non-interactive runs work.

Don't build interrupt-during-ReAct yet. Wait until you've actually used the
confirm-grade interrupt and learned what's annoying.

### 5.7 (P2) Cache BM25 retriever per session

Build it once in `app.py`'s `on_chat_start` and in `run_eval.py`'s setup
phase, pass it to `retrieve()`.

### 5.8 (P2) Consolidate the document representation

Drop the `Doc` dataclass; use `TextNode` end-to-end. Removes
`if hasattr(doc, "metadata") else {}` checks in `app.py`.

### 5.9 (P2) Promote A3/A4 rerankers to LlamaIndex `NodePostprocessor`

Standard LlamaIndex interface. Cleaner seams, traceable, swappable.

### 5.10 (P3) Move the EMA-specific acronym hint out of ReAct prompt

Delete the line; rely on query expansion (which now runs for ReAct too, once
A1 is universal).

### 5.11 (P3) Move `results/` to Nextcloud

Currently `results/<run_id>/` lives in the repo. Move to
`~/Nextcloud/Datasets/ema_nlp/results/`; replace with a symlink.

---

## 6. LlamaIndex Workflows vs LangGraph — verdict

**Stay with LlamaIndex Workflows.** You already decided this on 2026-05-22
for good reasons; the code confirms it.

For **structured retrieval over an indexed corpus** (80% of your project),
LlamaIndex wins. The LangGraph experiment failed not because LangGraph is
bad but because the LangChain `Document` ↔ LlamaIndex `TextNode` bridge
stripped metadata. Two frameworks → impedance mismatch.

The one thing LangGraph still does better is *durable cross-session agent
state* via `MemorySaver` / `SqliteSaver`. You don't need that. Revisit only
if your roadmap shifts toward "resume yesterday's agent run today with full
state."

Phoenix + OpenInference auto-instrumentation gives you observability
without framework lock-in. If you ever leave LlamaIndex, the traces and
labels stay.

---

## 7. Revised roadmap (6 weeks of evenings)

Re-sequenced to put HITL infrastructure earlier, since you said it's
critical for both SME thought-chain review and final-answer rating.

**Week 1 — unify eval and orchestration**
- §5.1 wire `run_eval.py` to workflow registry, add `orchestration:` block.
- Delete `answer_gen.py`.
- Re-run baselines A0, A0+ through workflows; confirm identical numbers.

**Week 2 — fix CRAG and roll out role-based LLM config**
- §5.2 per-document grader with `missing_facts`.
- §5.5 role/model split in `models.yaml`.
- Add `openai_compatible` provider (so local Qwen on the 3090 is a one-line
  config swap when you want it).
- Re-run CRAG variants; report does CRAG help on T2/T3.

**Week 3 — native ReAct workflow + Phoenix label schemas**
- §5.4 hand-written ReAct Workflow with per-step events.
- §5.3 define Phoenix annotation configs; set up label vocabulary.
- Annotate one CRAG run and one ReAct run by hand; sanity check the UX.

**Week 4 — annotation export + first SME review session**
- §5.3 write `export_annotations.py` to JSONL on Nextcloud.
- Run 5 questions through each strategy, label every step, see what failure
  modes emerge.
- Decide whether to build §5.6 (runtime interrupt) based on whether
  post-hoc labelling is enough.

**Week 5 — clean up & ablation comparison**
- §5.7–§5.11: BM25 caching, doc representation, reranker as
  NodePostprocessor, acronym hint move, results to Nextcloud.
- Run full strategy comparison (Ablation A fixed at `simple_rag_zero`;
  separate workflow axis with A0+ retrieval).

**Week 6 — write up findings**
- T1/T2/T3/T4 per-strategy comparison.
- SME-labelled failure-mode breakdown (planning vs retrieval vs reasoning
  vs tool-use, per AgentHallu taxonomy).
- Decide v2 scope based on what hurts most.

**v2 (post-six-weeks)** — Ablation B (process rewards from accumulated
labels), few-shot injection from rated trajectories, DSPy if you have ≥50
rated runs, graph RAG only if cross-ref traversal proves insufficient.

---

## 8. Resolved & remaining design questions

**Resolved in this conversation:**

1. Ablation A × workflow = **stacked** (A1–A5 fixed on `simple_rag_zero`;
   workflows compared on A0+ retrieval).
2. Breaking CRAG comparability is **fine**.
3. SME reviews both thought chains and final answers; both granularities
   needed.
4. Nextcloud cache sharing is **intentional**.
5. Trace explorer = **Phoenix annotation queues** (not a custom build).
6. Chat UI stays Chainlit.
7. LLM swappability = **role-based config**, easy provider swap, Anthropic
   for now, local on 3090 later.
8. Project is **agentic RAG**, not graph RAG (fix README framing).

**Open, worth deciding before week 1:**

- **Should `tier_id` still exist as an alias, or break the API in week 2?**
  Mid-tier (`mid`) and frontier (`frontier`) are used in lots of places.
  Cleaner to break it; cheaper short-term to alias. Recommend break it once
  to avoid lingering "did I forget to convert this call site?" anxiety.
- **Label vocabulary depth.** I sketched five label types in §5.3. Worth
  using all five from day one, or start with `step_quality` only and add
  others as you find the friction? Recommend start narrow.
- **Phoenix instance hosting.** Currently Phoenix runs on whichever machine
  you started it on. If you label on home PC then continue on Elitebook, the
  labels are on the wrong machine. Either (a) always run Phoenix on home PC
  and Elitebook hits it via Tailscale, or (b) Postgres backing volume on
  Nextcloud. Recommend (a) — simpler.

If you want to start, I'd suggest §5.1 (wire `run_eval.py` to workflows) —
small, isolated, unlocks all the comparisons. We can talk through whether
the `orchestration:` YAML block is right before I touch any code.

See `CLAUDE_GUIDANCE.md` for instructions to Claude Code.
