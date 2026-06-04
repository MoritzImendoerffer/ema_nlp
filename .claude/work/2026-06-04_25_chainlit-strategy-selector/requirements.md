# Requirements — Chainlit strategy selector + WHOLE-documentation refresh

> **Scope extended 2026-06-04 (user):** "extend this work unit to the whole documentation — the whole
> documentation should be updated." This work unit now has **two threads**: **(A)** a refresh of the entire
> documentation set (DOC-001..011, driven by [`audit-findings.md`](audit-findings.md)), and **(B)** the
> original Chainlit strategy-selector feature + `docs/WORKFLOWS.md` (below). See `state.json`.

## Thread A — whole-documentation refresh

**Goal:** every doc reflects the current LlamaIndex-first Neo4j stack. An 11-agent staleness audit
(`audit-findings.md`) found **9 docs stale** against the post-refactor (LIR-001..012) + post-link-upgrade
(work unit 24) codebase, plus 2 low-priority touch-ups. The recurring stale themes:

1. **pgvector / FAISS-over-corpus / `EMA_RETRIEVER` / `harness/retrieve*.py` / `embed*.py` / `pg/`** shown
   as current — all **deleted** (LIR-012); selection is `EMA_INDEX_PROFILE`.
2. **"re-seam pending / verified on a CPU subset"** — LIR-009/010 done (2026-06-02), full graph built.
3. **`LINKS_TO` = 1.72M / 2.2M anchors** — now **99,520** (typed, main-content-scoped).
4. **`run_eval.py` / eval+judge suite / "9 workflows"** — eval suite **archived off-branch**; **7** workflows.

**Acceptance (Thread A):** no doc presents a deleted module/env-var/command as current; the LINKS_TO figure
is 99,520 everywhere it appears; the refactor is described as complete (not pending/subset); the eval suite
is consistently marked archived-pending-rebuild; `docs/WORKFLOWS.md` / `docs/RETRIEVAL_TRACKS.md` (current)
are left intact. Per-doc fixes + verdicts are in `audit-findings.md`; tasks are DOC-001..011 in `state.json`.

---

## Thread B — Chainlit strategy selector + strategy docs

Three asks from the user (original scope):

1. **Feature** — select the configuration (especially the **workflow strategy**) from the Chainlit
   **settings panel**, live.
2. **Inventory** — report which strategies are currently implemented (answered below + in `exploration.md`).
3. **Docs** — if no how-to exists (it doesn't), write good documentation on creating custom strategies
   (delivered: `docs/WORKFLOWS.md`).

## Background — two independent config axes (key distinction)

The app's config (the JSON the user pasted) spans **two orthogonal axes**:

- **Orchestration / workflow** (`ema.orchestration.strategy` + `prompt_strategy`) — *how the answer is
  produced* (retrieve→generate, ReAct loop, CRAG, …). Selected today by a **`cl.ChatProfile`** chosen at
  chat-start; **not** in the settings panel and **not** changeable mid-session.
- **Retrieval** (`ema.retrieval.strategy` + `ema.index.profile`) — *how documents are fetched*. Driven by
  the **index profile** (`EMA_INDEX_PROFILE` → `harness/configs/index/<name>.yaml`). Only `hierarchical`
  (over `property_graph`, profile `neo4j_hier`) is implemented today.

The user's "select the workflow (simpleRAG, RecursiveRetriever, …)" conflates the two: **simpleRAG is a
workflow**; **"RecursiveRetriever" is a retrieval concept** and is *not* implemented (the project uses the
custom `HierarchicalPGRetriever`; the nearest planned analogues are `hierarchical_links` / `pg_native`,
spec-only in `docs/RETRIEVAL_TRACKS.md`). The doc + UI must keep these axes clear.

## Implemented strategies (answer to #2)

| Axis | Implemented | Notes |
|------|-------------|-------|
| Orchestration workflows (7) | `simple_rag`, `react`, `crag`, `summarize_rag`, `crag_summarize`, `crag_review`, `react_review` | `WORKFLOW_REGISTRY` in `harness/workflows/registry.py` |
| Prompt strategies (3) | `zero_shot`, `few_shot`, `cot_self` | apply to `simple_rag`, `summarize_rag`, `crag`, `crag_summarize`, `crag_review`; **not** `react`/`react_review` (fixed `react_native`) |
| UI profiles today (9) | Simple RAG ×3 prompts + ReAct + CRAG + Summarize RAG + CRAG+Summarize + CRAG+Review + ReAct+Review | `_PROFILE_STRATEGY` in `app.py` (flattens workflow×prompt) |
| Retrieval strategies (1) | `hierarchical` (index kind `property_graph`, profile `neo4j_hier`) | `harness/indexing/registry.py`; one profile yaml exists |
| Retrieval — spec only | `vector_flat`, `hierarchical_links`, `property_graph_native` | `docs/RETRIEVAL_TRACKS.md` — not built |

## Functional requirements (feature, #1)

- **FR1** — The ChatSettings panel exposes a **workflow selector** (the 7 orchestration workflows, presented
  as the 9 flat profiles or as workflow + prompt widgets — see Decision D2) so the user can change the
  active workflow **live** (via `on_settings_update`, no chat restart).
- **FR2** — A **prompt-strategy selector** (`zero_shot`/`few_shot`/`cot_self`) is available; it is honored
  for the workflows that accept it and ignored (no error) for `react`/`react_review`.
- **FR3** — Changing the workflow/prompt in settings **rebuilds the session pipeline** in place
  (`_build_session_workflow`) and updates the session state used by `on_message`; the existing
  agent_model / temperature / retrieval_k / cache widgets keep working.
- **FR4** — The selected workflow/prompt is reflected on the **Phoenix span** (`config_attributes()`
  already emits `ema.orchestration.strategy`/`prompt_strategy`, so this is automatic once the pipeline is
  rebuilt with the chosen values).
- **FR5** — Initial values: the settings widgets are **seeded** from the chosen `ChatProfile` (or the
  `EMA_WORKFLOW_STRATEGY` default) at chat-start, so behavior is unchanged until the user edits settings.
- **FR6 (optional / future-aware)** — An **index-profile selector** populated by globbing
  `harness/configs/index/*.yaml` (only `neo4j_hier` today). Switching the profile requires reloading the
  index and is coupled to the P0 registry-`open`-dispatch gap (`docs/RETRIEVAL_TRACKS.md` §0.7); scope as a
  follow-up unless trivially single-valued. See Decision D3.

## Functional requirements (docs, #3)

- **FR7** — `docs/WORKFLOWS.md` explains the two axes, lists the implemented strategies, and gives a
  **step-by-step recipe** to add (a) a new orchestration workflow and (b) a new retrieval strategy, plus the
  `WorkflowRunner` contract, the `StartEvent` inputs, `config_attributes()`, prompt files, the composite
  pattern, and how to surface a new workflow in `app.py`. Cross-links `RETRIEVAL.md` §7 and
  `RETRIEVAL_TRACKS.md`.

## Non-functional requirements

- **NFR1** — No change to the retrieval/indexing layer; the feature is confined to `app.py` (UI wiring).
- **NFR2** — `react`/`react_review` must not break when a `prompt_strategy` is set (passed but ignored).
- **NFR3** — Phoenix-disabled and chat-resume paths keep working (settings rebuild is idempotent).
- **NFR4** — Docs are accurate to the live registries (verified against `--list` output, not guessed).

## Acceptance criteria

1. In a running app, opening the settings panel shows a workflow selector; changing it and saving makes the
   **next** answer use the new workflow (verifiable by the Phoenix span `ema.orchestration.strategy` and by
   behavior, e.g. CRAG's grade/rewrite steps appearing).
2. Selecting a prompt strategy changes `ema.orchestration.prompt_strategy`; `react`/`react_review` run
   unchanged regardless of the prompt setting.
3. agent_model / temperature / retrieval_k / cache still work after the change.
4. `docs/WORKFLOWS.md` exists, lists exactly the 7 workflows + 3 prompts + 1 retrieval strategy, and its
   "add a custom strategy" recipe matches the real builder/registry/prompt files.
5. No regression in `pytest` (app.py has no unit tests; the workflow registry tests stay green).

## Risks / decisions

- **D1 — ChatProfile vs ChatSettings ownership of the workflow.** Keep both (ChatProfile seeds, settings
  override live) vs move entirely to settings. *Lean: settings becomes the live source of truth; ChatProfile
  seeds the initial value (avoids two conflicting controls).*
- **D2 — One 9-item Select vs two widgets (workflow + prompt).** *Lean: two widgets (workflow Select [7] +
  prompt_strategy Select [3]) — cleaner and matches the registry; document that prompt is ignored for
  react/react_review.* Alternative: reuse the existing flat 9-profile list as a single Select (less code,
  but couples the two axes).
- **D3 — Index-profile selector.** Only `neo4j_hier` exists; switching profiles needs an index reload and
  the P0 open-dispatch refactor for non-`property_graph` kinds. *Lean: defer (or ship a single-option,
  disabled-looking Select) until Track A/B profiles land.*
- **R1 — `on_chat_resume`** also seeds strategy from thread tags; the settings seeding must stay consistent
  there.
