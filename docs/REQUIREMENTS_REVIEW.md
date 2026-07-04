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
executable code references them (verified). Offline tests: **413 passed / 2 skipped**;
only `tests/test_mongo_source.py` fails (needs the live MongoDB container).

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
- (d) ⚠️ Scaffolded but dead. `configs/retrieval/native.yaml` declares
  `sub_retrievers: [chunk_vector, cypher_template]` / `graph_mode` / `k`, but **no code
  consumes these fields** (finding F8); `native_pg.py` composes retriever *objects*, and no
  name→builder registry exists. Only one index profile (`neo4j_hier`) exists, and
  `load_index_profile` ignores `$EMA_CONFIG_DIR` (F9), unlike recipes/prompts.
- (e) ❌ Regressed. The deleted Workflow engine had a post-generation faithfulness review
  with a threshold + `passed` verdict (`CRAGReviewWorkflow`, `review_threshold: 0.6`). The
  recipe engine kept only the **scorer**: `JudgePolicy` = `{enabled, judges, model_role}`
  — no threshold, no gate, no retry; a low score changes nothing.
  `docs/TARGET_ARCHITECTURE.md:113` explicitly downgraded this ("'review' becomes a
  judge/scorer pass"); `models.yaml`'s `reviewer` role is dead config (F10).

**Gaps:** multi-agent sequences (b), graph-navigation tools (c), a working
sub-retriever/profile selection story (d), reviewer-in-the-loop (e).

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

**Caveats (from the audit):** `neo4j_hier.yaml` ships `scope.limit: 50` — a rebuild
footgun (F11); the `embed_model:` field in the profile is decorative — the embedder comes
from env/defaults only (F12), and the few-shot query cache stores vectors with **no
embedding-model provenance** (silent cross-model mixing if `EMA_EMBED_MODEL` changes);
`app.py` mutates process-global `EMA_INDEX_PROFILE` (F13).

**Open question — R3-Q1:** should the index profile be the *single source of truth* for
the embedding model (wire `embed_model` through, stamp it into the cache sidecar), so R3
stays true under model changes? (Recommended: yes.)

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
- ⚠️ But four audit findings undermine "honest inspection":
  - **F1** — the advertised acronym query-expansion is a silent no-op in *every* path,
    while traces stamp `query_transform=acronym` (dishonest stamping, empirically confirmed).
  - **F3** — the **offline** `mlflow.genai` faithfulness judge never receives the retrieved
    context (`_VAR_MAP` maps both `question` and `context` → `inputs`); its scores are
    meaningless. (The **inline** judge is fine — it gets real `context_passages`.)
  - **F14** — `ema.recipe` lands on a *child* span, not the trace root → trace-level
    filtering by recipe (the stated purpose) needs span drilling.
  - **F15** — experiment-name drift: the app honors `EMA_MLFLOW_EXPERIMENT`, the demo
    script/eval hardcode `ema_nlp` → human and judge assessments can land in different
    experiments, breaking `align_judge`'s premise.
- ❌ The "use judges to find better orchestrations" *loop* has no vehicle: there is no eval
  runner that takes a recipe (F5/R6), and `bootstrap.py`'s pieces don't compose (default
  judge scores 0.0 → `judge_filter(min_score=4.0)` discards everything, F16).

**Open question — R5-Q1:** what is the unit of comparison you want in MLflow — per-turn
traces filtered by `ema.recipe` (interactive exploration), or named eval *runs* (recipe ×
benchmark → metrics table)? Both are intended; the second doesn't exist yet (→ R6).

**Proposed direction:** fix F1/F3/F14/F15 (small diffs, they're all "make the stamp match
reality"), then build the recipe-driven eval runner (R6) — inspection is already good;
*comparison* is what's missing.

---

## 6. R6 — Reproducible, version-controlled experiments

**Statement (draft):** experiments (instructions, orchestrations, retrieval settings) are
reproducible and version-controlled: same recipe + same data ⇒ same setup, and every
result can be traced back to the exact config that produced it.

**Current state (verified):**
- ✅ The *inputs* are version-controllable: recipes, prompts, index profiles, model roles,
  judge prompts are all files in git; the effective config is stamped on traces;
  `record_answer_run` dumps resolved params per recorded run.
- ❌ The *experiment vehicle* is missing/broken:
  - **F5 (top finding):** `build_predict_fn` cannot consume what `build_recipe` produces
    (`AgentWorkflowAdapter` has no `.run` and is not callable → `TypeError`). The only
    eval-compatible entry (`build_session`) **bypasses recipes** and hardcodes divergent
    defaults (pipeline `native`, `configs/agent/regulatory.yaml`). So "run recipe X on
    benchmark Y" is currently *impossible* — the core of R6.
  - The benchmark suite itself was removed from this branch (archived on
    `archive/pre-llamaindex-refactor`); the `results/<run_id>/` + config-dump convention
    (CLAUDE.md) has no current implementation.
  - `$EMA_CONFIG_DIR` recipes live *outside* the repo — reproducibility of external
    recipes is the owner's responsibility (worth a documented convention: a separate
    config repo, or "external is for scratch only; promoted recipes move into the repo").
  - `uv.lock` is currently untracked (git status `??`) — commit it for env reproducibility.
- ⚠️ Two composition paths (`build_recipe` vs `build_session`, F6) mean "the same" agent
  can be materially different depending on entry point — a direct reproducibility hazard.

**Open question — R6-Q1:** is MLflow the system of record for results (runs + artifacts),
or do you also want the file-based `results/<run_id>/` convention from CLAUDE.md? Pick one
primary to avoid a third half-implemented store.

**Proposed direction:** make `AgentWorkflowAdapter` satisfy the eval contract (or teach
`build_predict_fn` the `invoke` contract), delete/absorb `build_session` +
`configs/agent/*.yaml` so **one** composition path exists, resurrect a minimal benchmark
runner (`recipe × benchmark.jsonl → MLflow run with per-type metrics`), and commit `uv.lock`.

---

## 7. R7 — Output formats as Pydantic models, selected via config

**Statement (draft):** the desired output structure of a setup is defined by a Pydantic
model and selected (and ideally *defined*) via config files.

**Current state: ❌ aligned in name only** (the audit's biggest goal gap):
- `recipe.orchestration.output_schema` exists and is plumbed to the agent's `output_cls` —
  but the registry (`harness/agents/registry.py:21` `_OUTPUT_SCHEMAS`) contains **exactly
  one** entry (`RegulatoryAnswer`); `Substance` exists in `harness/schemas/` but is not
  registered.
- Unknown schema names **silently fall back** to `RegulatoryAnswer` while the trace stamps
  the raw YAML string → a typo runs one schema and stamps another (F2, dishonest stamping).
- Even a registered second schema would not survive the run: `coerce_answer`/`_to_answer`,
  `AgentSession.arun`, the adapter, citation rebuilding, and the judges all hardcode
  `RegulatoryAnswer`; a foreign structured result gets flattened to
  `RegulatoryAnswer(answer=str(...))`.
- There is no mechanism to *define* a schema in a config file at all.

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
| F1 | 🔴 | Acronym query-expansion silently dead in all paths (dict-parse of list-shaped YAML swallowed; `build_recipe` never passes acronyms; CWD-relative path) while traces stamp `query_transform=acronym` | `harness/agents/session.py:25-39`, `harness/recipes/build.py:66` |
| F2 | 🟠 | `output_schema` silent fallback to `RegulatoryAnswer` + downstream hardcoding; only one schema registered | `harness/agents/registry.py:21,41`, `harness/agents/runner.py:35-49` |
| F3 | 🔴 → ✅ fixed 2026-07-04 | Offline `mlflow.genai` faithfulness judge never sees context (`{{context}}`→`inputs`; predict_fn returns no passages) — scores meaningless; inline path OK. *Fix: `_VAR_MAP` context→outputs + `predict_fn` returns `context_passages` on every branch (adapter passthrough / `capture_search_nodes` around `.run`).* | `harness/eval/judges.py`, `harness/eval/predict.py` |
| F4 | 🔴 → ✅ fixed 2026-07-04 | Rated-trajectory cache: per-session `QueryCache()` + full-file rewrite on save → cross-session lost updates of entries and ratings (the few-shot learning signal). *Fix: process-wide `get_query_cache()` + `RLock` around mutations + atomic tmp/rename writes. Multi-process stays last-writer-wins (documented; app is single-process).* | `harness/query_cache.py`, `app.py` |
| F5 | 🔴 → ✅ fixed 2026-07-04 | Eval cannot consume recipes: `build_predict_fn` needs `.run`/callable; adapter has neither; only recipe-bypassing `build_session` works. *Fix: `build_predict_fn` now prefers the adapter's `invoke` contract; recipe × benchmark runner exists (`harness/eval/runner.py`, `scripts/run_eval.py`).* | `harness/eval/predict.py`, `harness/eval/runner.py` |
| F6 | 🟠 → ✅ fixed 2026-07-04 | Two divergent composition paths: `build_session` (agent YAML, pipeline=`native` hardcoded) vs `build_recipe` (recipes, pipeline per recipe). *Fix: `build_session` + `load_agent_config` + `configs/agent/*.yaml` deleted; `build_recipe` is the single composition path; `AgentConfig` is derived from the recipe.* | `harness/agents/session.py`, `harness/recipes/build.py` |
| F7 | 🔴 → ✅ fixed 2026-07-04 | Few-shot injection near-unreachable: `min_examples` default 3 never overridden; `k<3` recipes can never inject; not tunable from `FewshotPolicy`. *Fix: `FewshotPolicy.min_examples` (default 1), passed through by `app.py`, stamped on traces.* | `harness/recipes/config.py`, `harness/fewshot_inject.py`, `app.py` |
| F8 | 🟡 | Dead retrieval config: `sub_retrievers`/`graph_mode`/`k` in `native.yaml` have no consumer (three `k`s exist; one is live) | `harness/retrieval/config.py:41-43,68-70` |
| F9 | 🟡 | `load_index_profile` ignores `$EMA_CONFIG_DIR` (recipes/prompts honor it) | `harness/indexing/profiles.py:188` |
| F10 | 🟡 | Dead knobs stamped as effective: `judge.model_role` (judge role hardcoded), `fewshot.source`, `models.yaml` `reviewer` role unconsumed | `harness/eval/inline_judge.py:59`, `harness/recipes/config.py:31` |
| F11 | 🟡 | Checked-in default index profile ships `scope.limit: 50` — rebuild would ingest 50 docs | `harness/configs/index/neo4j_hier.yaml:20` |
| F12 | 🟡 | Profile `embed_model` decorative; query cache has no embedding-model provenance (silent space-mixing on model switch) | `harness/indexing/property_graph.py:69-75`, `harness/query_cache.py:34` |
| F13 | 🟡 | Process-global `EMA_INDEX_PROFILE` mutation can mis-stamp concurrent sessions' traces (self-contradicting trace) | `app.py:260`, `harness/agents/workflow_adapter.py:59` |
| F14 | 🟡 | `ema.recipe` stamped on child span, not trace root → recipe-level trace filtering needs drilling | `app.py:516-521`, `harness/recipes/build.py:84-87` |
| F15 | 🟡 | Experiment-name drift: app honors `EMA_MLFLOW_EXPERIMENT`; demo/eval hardcode `ema_nlp` → assessments split across experiments | `app.py:46`, `scripts/run_agent_demo.py:33`, `harness/eval/evaluate.py:19` |
| F16 | 🟡 | `bootstrap.py` pieces don't compose (judge=None → all-0.0 scores → `min_score=4.0` filter empties trainset; judge signature mismatch) | `harness/eval/bootstrap.py:27-50` |
| F17 | 🟡 → ✅ fixed 2026-07-04 | `corrective_search` returns the *last* retrieval, not best-so-far (comment claims otherwise); grader prompt demands `qa_id`s absent from its context; parse-error pseudo-fact fed to rewriter. *Fix: `grade_key` tracks best-so-far across cycles (ties→later); grader keys on the `[i]` document index; the parse-error sentinel is filtered out of rewrite prompts.* | `harness/retrieval/corrective.py`, `harness/tools/corrective_search.py` |
| F18 | 🟡 | Reviewer-in-the-loop regressed: old engine had threshold+`passed` gate (`CRAGReviewWorkflow`); recipes have score-only `JudgePolicy` — no gate/retry seam | `harness/recipes/config.py:47-61` (cf. deleted `harness/workflows/review.py`) |
| F19 | 🟡 → ✅ fixed 2026-07-04 | UI: cache toggle off silently kills few-shot + rating persistence; 👎-rated entries offered for reuse; `on_chat_resume` reverts to default recipe; failed profile switch leaves UI/pipeline disagreeing. *Fix: toggle now disables cache READS only (writes/ratings always persist, with a UI notice); reuse offers filter out rating<4; resume restores the thread's `chat_profile` recipe and says which recipe is active; failed switch snaps the settings panel back.* | `app.py` |
| F20 | 🟡 → ✅ fixed 2026-07-04 | Dead artifacts/deps: `scripts/generate_comparison_report.py` (consumes deleted engine's outputs), issue-generator scripts with pre-refactor plans, `ablations/a1_query_expansion.py` orphaned, empty `main.py`, unused deps (`llama-index-vector-stores-faiss`, `llama-index-retrievers-bm25`, `rank-bm25`), empty `harness/{workflows,pg,hitl}/` dirs (mask import errors as namespace pkgs), ~10 stale `WorkflowRunner` comments, `HARNESS_REFACTORS.md` is a Phoenix-era spec. *Fix: all deleted/cleaned; `uv.lock` committed. (The `__pycache__`-only dirs still need a manual `rm -rf harness/{workflows,pg,hitl,ablations}` — shell delete was declined during the session.)* | various |

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
| — | R1-Q3 reviewer: soft / hard / both | *a recommendataion seems to be easier to implement. In the final answer, certainty of the statements should be visible.* | |
| — | R2-Q1/Q2 subgraph purpose + attributes | *I do not have a clear strategy at the moment. It could be simple keywords to add, links from substance links or event an ontology. The purpose would be to improve the scope of the retrieval.* | |
| — | R3-Q1 embed-model single source of truth | *I stick to your recommendations, yes. "the index profile should be the single source of truth for the embedding model"* | |
| — | R4-Q1/Q2 external-tool policy + citation marking | *I stick to your recommendation, yes it should be clear where the context came from and it should be possible to define what is allowed* | |
| — | R5-Q1 comparison unit (traces vs eval runs) | *i agree with your recommendations* | |
| — | R6-Q1 system of record for results | *I would to for MLFlow to be the primary system of record for results.* | |
| — | R7-Q1 schema option A/B | *I stick to the recommendations* | |
| 2026-07-04 | R6 experiment vehicle | Landed: `harness/eval/runner.py` + `scripts/run_eval.py` — recipe × `benchmark/benchmark.jsonl` (45 Qs, present on this branch) → one MLflow run per question type, tagged `ema.recipe`/`ema.benchmark`/`ema.question_type`. MLflow = system of record per R6-Q1. Runtime verification pending (GPU host). | this branch |
