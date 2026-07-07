# Requirements ↔ Codebase Review (working document)

> **Status: DRAFT — living document.** Created 2026-07-02 from (a) the owner's requirement
> statements (given informally in chat, restated below for refinement) and (b) a full
> codebase audit of branch `claude/agentic-rag-foundation` (three parallel deep reviews +
> test run, 2026-07-02). **This is the document we edit together**: refine the requirement
> wording, answer the open questions, strike or accept the proposed directions, and promote
> the result into `docs/TARGET_ARCHITECTURE.md` / `DECISIONS.md` once stable.
>
> How to work on it: each requirement has ①  a *statement* (owner-editable), ② the *verified
> current state*, ③ *gaps*, ④ *open questions* (owner answers inline), ⑤ a *proposed
> direction* (accept / reject / edit). Cross-cutting audit findings live in §9 with stable
> IDs (`F1…`) that the requirement sections reference.

---

## 0. Orientation — where the codebase actually is (2026-07-02)

For re-orientation after the refactor series. One paragraph, verified against code:

There is **one engine**: a LlamaIndex `FunctionAgent`. A **recipe**
(`harness/configs/recipes/*.yaml`, 7 built-ins, external override via `$EMA_CONFIG_DIR`)
configures it: system prompt + toolset (from the tool registry: `ema_search`,
`corrective_search`, `resolve_substance`) + output schema name + index profile + optional
retrieval pipeline (query-transform/rerank) + few-shot policy + optional inline judge.
`build_recipe` (`harness/recipes/build.py`) assembles agent + retriever + LLM and wraps it
in `AgentWorkflowAdapter` (`invoke/ainvoke → {answer_text, docs, answer, context_passages}`).
The Chainlit app selects recipes from a dropdown; MLflow autolog + a per-turn span trace
every run; 👍/👎 lands as MLflow trace assessments and rates the FAISS few-shot cache.
Retrieval is exclusively the Neo4j `PropertyGraphIndex` (79,882 docs). The old Workflow
engine, Phoenix tracing, and the pgvector/FAISS retrieval stack are **deleted** — no
executable code references them (verified). Offline tests: **432 passed / 2 skipped**
(as of 2026-07-04); only `tests/test_mongo_source.py` fails (needs the live MongoDB container).

Key docs: `docs/RECIPES.md` (current), `docs/RAG_TECHNIQUES.md` (current),
`docs/TARGET_ARCHITECTURE.md` (mostly current, but see R1/R-review divergence),
`docs/WORKFLOWS.md` + `ONBOARDING.md` + `ARCHITECTURE.md` (banner-flagged historical/stale).

---

## 1. R1 — Configurable agentic RAG setups

**Statement (draft — owner, please refine):** I can define different agentic RAG setups
purely by configuration, without knowing in advance which will win:
- (a) simple RAG = a single tool call into a deterministic pipeline;
- (b) CRAG variants — including as a **sequence of agents and tool calls**;
- (c) search expansion over the node hierarchy / a topological map of the document network
  (page→PDF links, section trees) as an agent-callable capability;
- (d) LlamaIndex-native retrieval strategies over the property graph (recursive retrieval,
  small-to-big, cypher/keyword sub-retrievers) selectable per setup;
- (e) a final **reviewer** with configurable instructions.

**Current state (verified):**
- (a) ✅ Works. `naive_rag` recipe = agent + one `ema_search` call into the deterministic
  retrieve(+optional transform/rerank) pipeline.
- (b) ⚠️ Partial. CRAG exists as a *bounded deterministic loop inside one tool*
  (`corrective_search`, single-sourced in `harness/retrieval/corrective.py`) driven by one
  agent. A CRAG as a **sequence of agents** is *not expressible*: the recipe schema has
  exactly one agent slot; multi-agent orchestration (LlamaIndex `AgentWorkflow` with
  several agents / handoffs) is not exposed. This is a deliberate consequence of the
  2026-06-25 "single-engine" decision — see Open question R1-Q1.
- (c) ❌ Not agent-visible. The retriever *internally* does small-to-big + 1-hop `LINKS_TO`
  expansion (index profile `neo4j_hier`), but there is **no graph-navigation tool** the
  agent can call (`follow_links` is named in TARGET_ARCHITECTURE §5 as an example but was
  never built). The agent cannot deliberately walk the topology.
- (d) ⚠️ Object-level only (by choice). The dead `sub_retrievers`/`graph_mode`/`k` config
  fields were **deleted 2026-07-05** (F8 — per the "delete or build, not half-way" rule);
  `native_pg.py` remains the object-composition seam until a config surface is justified.
  Only one index profile (`neo4j_hier`) exists, but profiles now honor `$EMA_CONFIG_DIR`
  (F9 fixed), so external profiles can be added without touching the source.
- (e) ✅ Restored as a *soft* reviewer (F18, fixed 2026-07-05 per owner R1-Q3):
  `JudgePolicy.{threshold, on_fail: annotate}` — a below-threshold (or unscorable) answer
  ships with a visible ⚠️ recommendation note, the verdict is stamped
  (`ema.judge.passed`), and model confidence is shown in the final message. Hard
  block/retry remains deferred (an unimplemented `on_fail` is a config error). The
  `reviewer` role is bindable via `judge.model_role` (F10 fixed).

**Gaps:** multi-agent sequences (b), graph-navigation tools (c) — both awaiting the
R1-Q1/R1-Q2 strategy decisions.

**Open questions (owner):**
- **R1-Q1 (the big one):** Do you need true *multi-agent sequences* (agent → agent
  handoffs), or is "one agent + deterministic tools + prompt-prescribed order" enough for
  the setups you foresee? The single-engine decision (2026-06-25, DECISIONS.md) currently
  forbids the former. Options: (i) keep single-agent, encode sequences as tools;
  (ii) extend recipes with an optional `agents:` list mapped onto LlamaIndex
  `AgentWorkflow` (native multi-agent, still one *framework*); (iii) defer until a
  benchmark failure demands it (the CLAUDE.md complexity rule).
- **R1-Q2:** For topology-aware expansion (c): should the *agent* decide when to walk the
  graph (a `follow_links`/`expand_neighbors`/`get_document_outline` tool), or should the
  walk stay *inside* the retriever (bigger `path_depth`, typed-edge filters) configured per
  index profile? Or both?
- **R1-Q3:** Reviewer (e): soft (a `review_answer` tool + prompt instructions — advisory,
  agent may ignore it), hard (adapter-level gate: `JudgePolicy.threshold` +
  `on_fail: annotate|retry`, deterministic), or both? (Analysis 2026-07-02: a tool cannot
  intercept the agent's *final* output, so "block/never ship below X" requires the hard
  seam.)

**Proposed direction:** keep the single-`FunctionAgent` engine as default; add
(1) a `review_answer` tool + `JudgePolicy.{threshold,on_fail}` (both flavors, tiny diffs);
(2) 1–2 graph-navigation tools reading the existing `LINKS_TO`/`PARENT_OF` edges;
(3) either delete the dead `sub_retrievers` config or build the name→builder registry it
implies — not leave it half-way; (4) decide R1-Q1 explicitly and record it in DECISIONS.md.

---

## 2. R2 — Property-graph evolution (attributes, subgraphs)

**Statement (draft):** I can later (a) enrich the property graph with additional
attributes/typed relations, and (b) generate smaller networks / subgraphs from e.g.
keyword search over attributes or other metadata (for scoped retrieval and/or inspection).

**Current state (verified):**
- (a) ✅ Seam exists and is runtime-verified: `harness/ontology/` (`schema.py`,
  `enrich.py`, `configs/ontology/ema.yaml`) maps a typed entity/relation schema onto a
  `SchemaLLMPathExtractor`; enrichment into Neo4j ran on the GPU host (T4, 2026-06-22).
  Corpus-wide Layer-2 extraction is deliberately deferred (TARGET_ARCHITECTURE §4.5).
- (b) ❌ Nothing exists. No subgraph-extraction API, no keyword/metadata-scoped retrieval
  surface, no named cypher templates (the `cypher_template` string in native.yaml is dead
  config, F8). Neo4j can do all of this; `harness/` exposes none of it.

**Open questions (owner):**
- **R2-Q1:** What are subgraphs *for* — (i) scoped retrieval ("only search within the
  nitrosamines cluster"), (ii) analysis/visualization, (iii) building smaller derived
  indexes? The right mechanism differs: (i) = metadata filters / cypher retriever at query
  time; (iii) = an ingest-time `scope` (already exists: `neo4j_hier.yaml` `scope.query`).
- **R2-Q2:** Which additional attributes do you foresee (document dates, procedure types,
  substance links from `resolve_substance`, IDMP concepts)? This decides whether enrichment
  stays LLM-extraction (`ontology/`) or needs a deterministic metadata backfill path.

**Proposed direction:** defer implementation (consistent with the "complexity must be
justified by a benchmark failure" lock) but *specify* it now: answer R2-Q1/Q2, then add a
`scope`/`filters` block to index profiles as the config surface, so R2 lands as
configuration rather than a new subsystem.

---

## 3. R3 — Agentic RAG runs on the stored EMA property graph

**Statement (draft):** all retrieval in the agentic RAG uses the stored EMA site data —
the Neo4j property graph (documents, chunks, section hierarchy, page→PDF link edges).

**Current state: ✅ met.** This is the strongest requirement. Every recipe's retrieval
flows through the `PropertyGraphIndex` (79,882 docs / 5.82M leaf embeddings / 99,520
`LINKS_TO` edges); `ema_search` and `corrective_search` are bound to the profile-built
retriever; `corpus.jsonl` is benchmark-only, as designed.

**Caveats (from the audit) — all resolved:** ~~`scope.limit: 50` footgun (F11); decorative
`embed_model` + no cache provenance (F12); process-global `EMA_INDEX_PROFILE` mis-stamping
(F13)~~ — fixed 2026-07-04/05, see §9.

**Open question — R3-Q1: ✅ decided (owner, 2026-07-02) and implemented (2026-07-05):**
the index profile is the single source of truth for the embedding model —
`profile.index.embed_model` drives `configure_embed_model` on the build/open/retriever
paths (`EMA_EMBED_MODEL` is fallback only), and the query-cache sidecar records the
embed model, backing the cache up and starting fresh on a model switch.

---

## 4. R4 — Optional external tools (web search, MCP servers)

**Statement (draft):** when *explicitly allowed*, a setup can include external tools —
web search, MCP servers (e.g. publication databases) — alongside the corpus tools.

**Current state:** the **tool registry is the right seam and works** (recipes select
tools by name; builders ignore kwargs they don't need), but: no external tool exists, no
MCP integration exists, and there is **no "explicitly allowed" concept** — nothing
distinguishes corpus-grounded tools from external ones, in config, at runtime, or on
traces. Under the current V1 scope locks (EMA-only content), an unmarked web-search tool
would also quietly violate the corpus boundary that the benchmark's contamination story
(LEAKAGE.md) depends on.

**Open questions (owner):**
- **R4-Q1:** What does "explicitly allowed" mean concretely — a recipe-level flag
  (`allow_external: true`), a per-tool `external: true` marking + app-level allowlist,
  an env gate, or all three?
- **R4-Q2:** Must externally-sourced evidence be distinguishable in the *answer*
  (citations flagged `source: web` vs `source: corpus`)? This touches R7 (the
  `Citation` schema would grow a field) and the eval design (lift metric assumes
  corpus-grounding).

**Proposed direction:** define the policy surface *before* the first external tool:
tag tool builders with `external: bool` in the registry, refuse to build a recipe whose
toolset includes external tools unless the recipe says `allow_external: true`, stamp
`ema.tools.external=true` on traces, and extend `Citation` with a source-kind field.
MCP client wiring is then just another registered builder.

---

## 5. R5 — Inspectability + judge-driven improvement

**Statement (draft):** for any run I can inspect the query, the full pipeline (tools
called, intermediate reasoning, retrieved passages), and use MLflow judges to compare
setups and improve instructions/orchestrations.

**Current state (verified):**
- ✅ MLflow autolog + an explicit per-turn span trace every UI turn and agent run; tool
  calls and LLM steps appear as nested spans; the **effective** (override-applied) recipe
  config is stamped on the turn span; 👍/👎 + inline judge scores attach to the trace as
  assessments; `align_judge` scaffolding exists to calibrate judges against human feedback.
- ✅ **The four "honest inspection" findings are fixed (2026-07-04):** F1 (acronym expansion
  live + honest stamping), F3 (offline faithfulness judge now receives `context_passages`
  from every predict path), F14 (`ema.recipe` is a searchable trace-level tag), F15 (shared
  `default_experiment()` resolver — no experiment split). See §9 for the fix details.
- ✅ The "use judges to find better orchestrations" loop has its vehicle: the recipe-driven
  eval runner exists (F5/R6 fixed — `harness/eval/runner.py`, `scripts/run_eval.py`).
  Remaining: `bootstrap.py`'s pieces still don't compose (default judge scores 0.0 →
  `judge_filter(min_score=4.0)` discards everything, F16 — open).

**Open question — R5-Q1:** what is the unit of comparison you want in MLflow — per-turn
traces filtered by `ema.recipe` (interactive exploration), or named eval *runs* (recipe ×
benchmark → metrics table)? Both are intended; the second doesn't exist yet (→ R6).

**Proposed direction:** ~~fix F1/F3/F14/F15 (small diffs, they're all "make the stamp match
reality"), then build the recipe-driven eval runner (R6)~~ — **done 2026-07-04**; what MLflow
shows is what ran, and per-recipe comparison runs exist. Next for R5: accumulate rated
traces and run `align_judge`.

---

## 6. R6 — Reproducible, version-controlled experiments

**Statement (draft):** experiments (instructions, orchestrations, retrieval settings) are
reproducible and version-controlled: same recipe + same data ⇒ same setup, and every
result can be traced back to the exact config that produced it.

**Current state (verified):**
- ✅ The *inputs* are version-controllable: recipes, prompts, index profiles, model roles,
  judge prompts are all files in git; the effective config is stamped on traces;
  `record_answer_run` dumps resolved params per recorded run.
- ✅ **The experiment vehicle exists (2026-07-04):**
  - **F5 fixed:** `build_predict_fn` consumes the `AgentWorkflowAdapter` `invoke` contract
    (and still accepts `.run`/callables); "run recipe X on benchmark Y" is
    `python scripts/run_eval.py --recipe X` — one MLflow run per question type, tagged
    `ema.recipe`/`ema.benchmark`/`ema.question_type` (`harness/eval/runner.py`).
    Runtime verification on the GPU host is still pending.
  - `benchmark/benchmark.jsonl` is on this branch (45 items); per R6-Q1, **MLflow is the
    system of record** for results (no `results/<run_id>/` file convention).
  - `$EMA_CONFIG_DIR` recipes live *outside* the repo — reproducibility of external
    recipes is the owner's responsibility (worth a documented convention: a separate
    config repo, or "external is for scratch only; promoted recipes move into the repo").
  - `uv.lock` is committed (2026-07-04).
- ✅ **F6 fixed:** `build_session` + `configs/agent/*.yaml` deleted — `build_recipe` is the
  single composition path, so entry point can no longer change what "the same" agent means.

**Open question — R6-Q1:** is MLflow the system of record for results (runs + artifacts),
or do you also want the file-based `results/<run_id>/` convention from CLAUDE.md? Pick one
primary to avoid a third half-implemented store.

**Proposed direction:** ~~make `AgentWorkflowAdapter` satisfy the eval contract, delete/absorb
`build_session` + `configs/agent/*.yaml`, resurrect a minimal benchmark runner, commit
`uv.lock`~~ — **all done 2026-07-04**. Next for R6: runtime-verify `scripts/run_eval.py` on
the GPU host, then closed-book baselines + the lift metric.

---

## 7. R7 — Output formats as Pydantic models, selected via config

**Statement (draft):** the desired output structure of a setup is defined by a Pydantic
model and selected (and ideally *defined*) via config files.

**Current state: ⚠️ partially fixed (2026-07-04)** (was the audit's biggest goal gap):
- ✅ **F2 fixed:** the registry is strict and extensible — `get_output_schema` raises
  `KeyError` on unknown names (no silent fallback; the stamp can't lie), and
  `register_output_schema`/`list_output_schemas` exist; **`Substance` is registered** as
  the second schema.
- ❌ Still open: a registered second schema would not fully survive the run —
  `coerce_answer`/`_to_answer`, `AgentSession.arun`, the adapter, citation rebuilding, and
  the judges still assume `RegulatoryAnswer`; a foreign structured result gets flattened to
  `RegulatoryAnswer(answer=str(...))`. Generalizing that plumbing to a small `BaseModel`
  protocol is the remaining R7-Option-A work (see R7-Q2).
- ❌ There is still no mechanism to *define* a schema in a config file (Option B, deferred).

**Open questions (owner):**
- **R7-Q1 (design fork):**
  - **Option A — code-defined, config-selected:** schemas remain Python classes (they need
    field descriptions/docstrings to steer the LLM anyway); the registry becomes honestly
    extensible (strict lookup — unknown name = hard error), and the runner/adapter/judge
    plumbing is generalized to `BaseModel` with a small protocol (e.g. "has `answer: str`;
    optionally has `citations`"). New schema = one Python file + one registry line.
  - **Option B — YAML-defined schemas:** a `configs/schemas/<name>.yaml` → dynamic
    `pydantic.create_model` (field name/type/description/default), searched via
    `$EMA_CONFIG_DIR` like recipes. True "define via config", at the cost of dynamic-model
    debuggability and limited validators.
  - Recommendation: **A first** (it fixes correctness and unblocks a second schema
    cheaply), **B layered on top** if config-only schema authoring proves necessary —
    B can reuse A's registry as its lookup.
- **R7-Q2:** which parts of the current answer contract are *invariant across schemas*?
  Citation provenance rebuilding (`citations_from_nodes`) and the sidebar rendering assume
  `citations`/`claims` fields; the judge assumes `answer` + context. Naming the invariant
  protocol is the real design work.

**Proposed direction:** Option A now (strict registry + generic plumbing + register
`Substance` as the proof), decide on B after the first real second-schema use case.

---

## 8. Requirement-numbering note

The owner's original message numbered two items "R4" and two "R5". Renumbered here as:
R4 = external tools/MCP, R5 = inspectability/judges, R6 = reproducibility, R7 = Pydantic
outputs. Owner: please confirm or re-order by priority.

---

## 9. Audit findings register (2026-07-02)

Stable IDs referenced above. Severity: 🔴 bug, 🟠 wiring gap / dishonest config, 🟡 debt.

| ID | Sev | Finding | Where |
|----|-----|---------|-------|
| F1 | 🔴 → ✅ fixed 2026-07-04 | Acronym query-expansion silently dead in all paths (dict-parse of list-shaped YAML swallowed; `build_recipe` never passes acronyms; CWD-relative path) while traces stamp `query_transform=acronym`. *Fix: `harness/retrieval/acronyms.py` (`QueryExpander`, context-aware) + shipped `harness/configs/retrieval/acronyms.yaml`; the default transform loads it and raises if missing.* | `harness/retrieval/acronyms.py`, `harness/retrieval/transforms.py` |
| F2 | 🟠 → ✅ fixed 2026-07-04 | `output_schema` silent fallback to `RegulatoryAnswer` + downstream hardcoding; only one schema registered. *Fix: strict registry (`get/register/list_output_schemas`, unknown = `KeyError`); `Substance` registered as the second schema. Downstream `BaseModel`-generalization remains R7 work.* | `harness/agents/registry.py` |
| F3 | 🔴 → ✅ fixed 2026-07-04 | Offline `mlflow.genai` faithfulness judge never sees context (`{{context}}`→`inputs`; predict_fn returns no passages) — scores meaningless; inline path OK. *Fix: `_VAR_MAP` context→outputs + `predict_fn` returns `context_passages` on every branch (adapter passthrough / `capture_search_nodes` around `.run`).* | `harness/eval/judges.py`, `harness/eval/predict.py` |
| F4 | 🔴 → ✅ fixed 2026-07-04 | Rated-trajectory cache: per-session `QueryCache()` + full-file rewrite on save → cross-session lost updates of entries and ratings (the few-shot learning signal). *Fix: process-wide `get_query_cache()` + `RLock` around mutations + atomic tmp/rename writes. Multi-process stays last-writer-wins (documented; app is single-process).* | `harness/query_cache.py`, `app.py` |
| F5 | 🔴 → ✅ fixed 2026-07-04 | Eval cannot consume recipes: `build_predict_fn` needs `.run`/callable; adapter has neither; only recipe-bypassing `build_session` works. *Fix: `build_predict_fn` now prefers the adapter's `invoke` contract; recipe × benchmark runner exists (`harness/eval/runner.py`, `scripts/run_eval.py`).* | `harness/eval/predict.py`, `harness/eval/runner.py` |
| F6 | 🟠 → ✅ fixed 2026-07-04 | Two divergent composition paths: `build_session` (agent YAML, pipeline=`native` hardcoded) vs `build_recipe` (recipes, pipeline per recipe). *Fix: `build_session` + `load_agent_config` + `configs/agent/*.yaml` deleted; `build_recipe` is the single composition path; `AgentConfig` is derived from the recipe.* | `harness/agents/session.py`, `harness/recipes/build.py` |
| F7 | 🔴 → ✅ fixed 2026-07-04 | Few-shot injection near-unreachable: `min_examples` default 3 never overridden; `k<3` recipes can never inject; not tunable from `FewshotPolicy`. *Fix: `FewshotPolicy.min_examples` (default 1), passed through by `app.py`, stamped on traces.* | `harness/recipes/config.py`, `harness/fewshot_inject.py`, `app.py` |
| F8 | 🟡 → ✅ fixed 2026-07-05 | Dead retrieval config: `sub_retrievers`/`graph_mode`/`k` in `native.yaml` have no consumer (three `k`s exist; one is live). *Fix: fields deleted outright (per R1(d): delete or build, not half-way); the pipeline config holds exactly what `assemble_agent` wires; retrieval `k` lives in the index profile.* | `harness/retrieval/config.py`, `harness/configs/retrieval/native.yaml` |
| F9 | 🟡 → ✅ fixed 2026-07-05 | `load_index_profile` ignores `$EMA_CONFIG_DIR` (recipes/prompts honor it). *Fix: profiles use the same `find_config` search path; external `index/` shadows built-ins.* | `harness/indexing/profiles.py` |
| F10 | 🟡 → ✅ fixed 2026-07-05 | Dead knobs stamped as effective: `judge.model_role` (judge role hardcoded), `fewshot.source`, `models.yaml` `reviewer` role unconsumed. *Fix: `run_inline_judges`/`Judge` honor `model_role` (a recipe can bind `reviewer`); unknown `fewshot.source` is a hard config error.* | `harness/eval/inline_judge.py`, `harness/judge.py`, `harness/recipes/config.py` |
| F11 | 🟡 → ✅ fixed 2026-07-05 | Checked-in default index profile ships `scope.limit: 50` — rebuild would ingest 50 docs. *Fix: shipped default is `limit: null` (full corpus, matching the live graph); caps belong in `$EMA_CONFIG_DIR` override profiles; regression test added.* | `harness/configs/index/neo4j_hier.yaml` |
| F12 | 🟡 → ✅ fixed 2026-07-05 | Profile `embed_model` decorative; query cache has no embedding-model provenance (silent space-mixing on model switch). *Fix (R3-Q1 yes): the profile's `embed_model` is passed to `configure_embed_model` on build/open/retriever paths (env is fallback only); the cache sidecar records the embed model and on mismatch backs the old files up (`*.bak-<model>`) and starts fresh.* | `harness/indexing/property_graph.py`, `harness/indexing/build.py`, `harness/query_cache.py` |
| F13 | 🟡 → ✅ fixed 2026-07-04 | Process-global `EMA_INDEX_PROFILE` mutation can mis-stamp concurrent sessions' traces (self-contradicting trace). *Fix: adapter stamps the recipe's resolved profile; the app's turn span stamps the SESSION's profile.* | `harness/agents/workflow_adapter.py`, `app.py` |
| F14 | 🟡 → ✅ fixed 2026-07-04 | `ema.recipe` stamped on child span, not trace root → recipe-level trace filtering needs drilling. *Fix: `tag_current_trace()` stamps `ema.recipe` as a trace-level tag (searchable via `mlflow.search_traces`).* | `harness/obs/tracing.py` |
| F15 | 🟡 → ✅ fixed 2026-07-04 | Experiment-name drift: app honors `EMA_MLFLOW_EXPERIMENT`; demo/eval hardcode `ema_nlp` → assessments split across experiments. *Fix: shared `default_experiment()` resolver used by app / demo / eval / `AgentSession`.* | `harness/obs/runs.py` |
| F16 | 🟡 → ✅ fixed 2026-07-05 | `bootstrap.py` pieces don't compose (judge=None → all-0.0 scores → `min_score=4.0` filter empties trainset; judge signature mismatch). *Fix: unjudged exemplars carry `score=None` and `judge_filter` refuses them loudly; `faithfulness_judge()` provides a compatible `(question, prediction)->float` judge that grades against the prediction's `context_passages` (composes with F3).* | `harness/eval/bootstrap.py` |
| F17 | 🟡 → ✅ fixed 2026-07-04 | `corrective_search` returns the *last* retrieval, not best-so-far (comment claims otherwise); grader prompt demands `qa_id`s absent from its context; parse-error pseudo-fact fed to rewriter. *Fix: `grade_key` tracks best-so-far across cycles (ties→later); grader keys on the `[i]` document index; the parse-error sentinel is filtered out of rewrite prompts.* | `harness/retrieval/corrective.py`, `harness/tools/corrective_search.py` |
| F18 | 🟡 → ✅ fixed 2026-07-05 | Reviewer-in-the-loop regressed: old engine had threshold+`passed` gate (`CRAGReviewWorkflow`); recipes have score-only `JudgePolicy` — no gate/retry seam. *Fix (per owner R1-Q3: soft/recommendation): `JudgePolicy.{threshold,on_fail=annotate}` + `review_verdict()` — below-threshold or unscorable answers ship with a visible ⚠️ caution; verdict stamped as `ema.judge.passed`; model confidence shown in the final message; `agentic_judged` recipe sets `threshold: 3`. Hard block/retry deferred (unimplemented `on_fail` = config error). Recorded in DECISIONS.md.* | `harness/recipes/config.py`, `harness/eval/inline_judge.py`, `app.py` |
| F19 | 🟡 → ✅ fixed 2026-07-04 | UI: cache toggle off silently kills few-shot + rating persistence; 👎-rated entries offered for reuse; `on_chat_resume` reverts to default recipe; failed profile switch leaves UI/pipeline disagreeing. *Fix: toggle now disables cache READS only (writes/ratings always persist, with a UI notice); reuse offers filter out rating<4; resume restores the thread's `chat_profile` recipe and says which recipe is active; failed switch snaps the settings panel back.* | `app.py` |
| F20 | 🟡 → ✅ fixed 2026-07-04 | Dead artifacts/deps: `scripts/generate_comparison_report.py` (consumes deleted engine's outputs), issue-generator scripts with pre-refactor plans, `ablations/a1_query_expansion.py` orphaned, empty `main.py`, unused deps (`llama-index-vector-stores-faiss`, `llama-index-retrievers-bm25`, `rank-bm25`), empty `harness/{workflows,pg,hitl}/` dirs (mask import errors as namespace pkgs), ~10 stale `WorkflowRunner` comments, `HARNESS_REFACTORS.md` is a Phoenix-era spec. *Fix: all deleted/cleaned; `uv.lock` committed; the `__pycache__`-only dirs `harness/{workflows,pg,hitl,ablations}` physically removed 2026-07-05.* | various |

**Verified-solid (for calibration):** offline test suite green and accurate; recipe/tool/
prompt/model-role cross-references all resolve; CRAG logic single-sourced; contextvar node
capture correct (nested scopes, `finally` resets); `recipe.default`, `judge.enabled`,
`fewshot.enabled` gating in `app.py` correct; rating semantics self-consistent
(👍=5.0/👎=1.0 vs `min_rating: 4`); feedback→trace attachment race-free on the happy path;
"current" docs (RECIPES, AGENTIC_GUIDE, RAG_TECHNIQUES, README) match the code.

---

## 10. Proposed sequencing (to refine together)

1. **Truth first (small diffs, restores trust in traces):** F1, F2-strict-lookup, F3, F14,
   F15 — after this, what MLflow shows is what ran.
2. **Unblock experimentation (R6/R5):** F5 + F6 (one composition path; adapter satisfies
   eval contract), minimal recipe×benchmark runner. This is the prerequisite for "find
   better orchestrations" and for justifying complexity by benchmark failures.
3. **Requirement decisions (this doc):** R1-Q1 (multi-agent?), R1-Q3 (reviewer flavor),
   R7-Q1 (schema option A/B), R4-Q1 (external-tool policy) → record in DECISIONS.md.
4. **Capability adds per decisions:** reviewer seam (F18), graph tools (R1c), schema
   registry generalization (R7), external-tool policy surface (R4).
5. **Feedback-loop correctness (when multi-user use matters):** F4, F7, F19.
6. **Hygiene sweep:** F8–F13, F16, F17, F20; commit `uv.lock`.

---

## 11. Decision log (fill in as we resolve)

| Date | Question | Decision | Recorded in |
|------|----------|----------|-------------|
| — | R1-Q1 multi-agent sequences | *one agent with multiple tool calls is probably enough, look for literature on this topic, latest recommentations seem to recommend single agent versus multi agent orchestrations. Where would an option for multiple agents make sense?* | |
| — | R1-Q2 graph walk: tool vs retriever-internal | *because the graph is so huge, I doubth the agent would be capable of doing that. So I guess a better way is to have specialized tools for that. Nevertheless, a tool could be another agent or LLM to handle e.g. complex ontologies or other complex topics. A simple recursive retriever or a single node topology algorithm might be better off than the main agent deciding which nodes to fetch. Let`s think together on a clear strategy* | |
| — | R1-Q3 reviewer: soft / hard / both | *a recommendataion seems to be easier to implement. In the final answer, certainty of the statements should be visible.* | DECISIONS.md "Reviewer-in-the-loop: soft recommendation" (implemented as F18, 2026-07-05) |
| — | R2-Q1/Q2 subgraph purpose + attributes | *I do not have a clear strategy at the moment. It could be simple keywords to add, links from substance links or event an ontology. The purpose would be to improve the scope of the retrieval.* | |
| — | R3-Q1 embed-model single source of truth | *I stick to your recommendations, yes. "the index profile should be the single source of truth for the embedding model"* | implemented as F12 (2026-07-05) |
| — | R4-Q1/Q2 external-tool policy + citation marking | *I stick to your recommendation, yes it should be clear where the context came from and it should be possible to define what is allowed* | |
| — | R5-Q1 comparison unit (traces vs eval runs) | *i agree with your recommendations* | |
| — | R6-Q1 system of record for results | *I would to for MLFlow to be the primary system of record for results.* | |
| — | R7-Q1 schema option A/B | *I stick to the recommendations* | |
| 2026-07-04 | R6 experiment vehicle | Landed: `harness/eval/runner.py` + `scripts/run_eval.py` — recipe × `benchmark/benchmark.jsonl` (45 Qs, present on this branch) → one MLflow run per question type, tagged `ema.recipe`/`ema.benchmark`/`ema.question_type`. MLflow = system of record per R6-Q1. Runtime verification pending (GPU host). | this branch |
| 2026-07-07 | Citation attribution + SME review + export (extends R5 inspectability) | Landed per approved plan: verbatim-claim span attribution (`harness/attribution.py`), clickable `[n]` markers in chat, persistent CitationReview element with per-citation SME verdicts → MLflow assessments (`log_citation_feedback`), config-driven MD/HTML export (`harness/export/`), `doc_type_priority` postprocessor. Research verdict: in-chat review beats dedicated tools (MLflow Review App Databricks-gated; Argilla maintenance mode; Label Studio/Langfuse = second service without span highlighting). | DECISIONS.md (3 entries, 2026-07-07); `docs/CITATIONS.md` |
