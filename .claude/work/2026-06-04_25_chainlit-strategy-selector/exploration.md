# Exploration — Chainlit strategy selector

## 1. How the app selects a workflow today (and why it's not in the panel)

`app.py` has **two** config surfaces:

- **`@cl.set_chat_profiles` → `cl.ChatProfile`** (app.py:216): renders the 9 `_PROFILE_STRATEGY` display
  names as a **top-of-chat profile dropdown**. The chosen profile is read in `on_chat_start`
  (`cl.user_session.get("chat_profile")`, app.py:335) → mapped to `(strategy, prompt_strategy)` → stored in
  `cl.user_session` as `strategy`/`prompt_strategy`. **This is the only workflow control, and it is fixed
  for the session** (changing it starts a new chat).
- **`cl.ChatSettings`** (`_make_chat_settings`, app.py:281): the **right-hand settings panel**. Today it
  holds only `agent_model`, `temperature`, `retrieval_k`, `cache_enabled`. `@cl.on_settings_update`
  (app.py:407) rebuilds the pipeline from these — but reads `strategy`/`prompt_strategy` **from the session**
  (set by the ChatProfile), not from the settings dict. So the workflow cannot be changed in the panel.

The pipeline is built by **`_build_session_workflow(index, *, strategy, prompt_strategy, model_name,
temperature, retrieval_k)`** (app.py:254) → `get_llm_for_model` + `load_index_profile(EMA_INDEX_PROFILE)` +
`build_retriever` + `get_workflow(strategy, retriever=…, llm=…, prompt_strategy=…)`. **Everything needed to
switch the workflow live is already a parameter of this function** — the only gap is *plumbing the choice
from a settings widget into it*.

## 2. The change is confined to `app.py` (UI plumbing only)

| Location | Change |
|----------|--------|
| `_make_chat_settings` (281) | Add a `Select` for **workflow** (the 9 profile names, or 7 strategies) and a `Select` for **prompt_strategy** (`zero_shot`/`few_shot`/`cot_self`). Optional: an index-profile `Select` (D3). |
| `_DEFAULT_SETTINGS` (311) | Seed `workflow`/`prompt_strategy` from the chat profile (or `EMA_WORKFLOW_STRATEGY`). |
| `_settings_to_pipeline_kwargs` (303) | Map the new widgets → `strategy` + `prompt_strategy` (in addition to model/temp/k). |
| `on_settings_update` (407) | Read `strategy`/`prompt_strategy` from `settings` (not the session), rebuild, and **update** `cl.user_session["strategy"/"prompt_strategy"]`. |
| `on_chat_start` / `on_chat_resume` (321/365) | Seed the settings widgets' initial values from the resolved profile so the panel shows the active workflow; otherwise unchanged. |

No change to `harness/` — `get_workflow` already validates the strategy and forwards `prompt_strategy` via
`**kwargs` (registry.py:148); workflows that ignore it (`react`, `react_review`) simply don't read it.
`config_attributes()` on each workflow already stamps `ema.orchestration.strategy`/`prompt_strategy`
(simple_rag.py:76, crag.py:164, composites.py:104…), so Phoenix reflects the live choice for free once the
pipeline is rebuilt.

## 3. The builder/registry pattern (for the docs + the widget values)

- **Registry:** `WORKFLOW_REGISTRY: dict[str, builder]` (registry.py) — builder signature
  `(retriever, llm, **kwargs) -> WorkflowRunner`. `get_workflow(name, *, retriever, llm, prompt_strategy,
  **kwargs)` dispatches; `list_workflows()` enumerates. Live: `crag, crag_review, crag_summarize, react,
  react_review, simple_rag, summarize_rag`.
- **A workflow** is a LlamaIndex `Workflow` with event-driven `@step`s (e.g. `SimpleRAGWorkflow`
  retrieve→generate; `ReActNativeWorkflow` think/act/observe/finish per-step for Phoenix spans). Each
  exposes `config_attributes() -> dict` (the `ema.*` span keys) and returns `{"answer_text", "docs", …}`.
- **`WorkflowRunner`** (utils.py:138) wraps a workflow: `invoke`/`ainvoke(inputs)`; opens the OTel span and
  calls `_stamp_span` (config_attributes + `run_id`/`source`). `StartEvent` inputs used by `app._run_pipeline`:
  `question`, `few_shot_context`, `run_id`, `source`.
- **Prompt variants:** `load_system_prompt(strategy)` reads `_PROMPT_FILES` (utils.py:30) →
  `harness/prompts/system_{zero_shot,few_shot_sme,cot_self}.md`. `extract_answer` strips the CoT block.
  Adding a 4th prompt = a new file + one `_PROMPT_FILES` entry + a value in the workflow's
  `_VALID_STRATEGIES` (no registry change — per the `DECISIONS.md` "prompt_strategy as YAML field" decision).
- **Composites** (`composites.py`): `crag_summarize`/`crag_review`/`react_review` chain existing workflows;
  the pattern is the template for new multi-stage strategies.
- **Retrieval axis** (separate): `@register_index(kind)` / `@register_retriever(strategy)` +
  `harness/configs/index/<name>.yaml` + `EMA_INDEX_PROFILE`. See `docs/RETRIEVAL.md` §7 and
  `docs/RETRIEVAL_TRACKS.md` (vector_flat / hierarchical_links / pg_native specs).

## 4. "RecursiveRetriever" — not implemented

The user listed "RecursiveRetriever" as a workflow option. It is **neither a registered workflow nor a
registered retriever** here. LlamaIndex ships a `RecursiveRetriever`, but this project deliberately uses the
custom `HierarchicalPGRetriever` (vector seed → small-to-big parent merge in one Cypher). The planned
graph-walking retrievers (`hierarchical_links`, `pg_native`) are the nearest analogues and are spec-only.
The settings selector should therefore offer the **7 real workflows**, and (when built) retrieval profiles
on the separate index-profile axis — not a "RecursiveRetriever" workflow.

## 5. Key files

- `app.py` — the only file the feature touches (`_make_chat_settings`, `_settings_to_pipeline_kwargs`,
  `on_settings_update`, `on_chat_start`, `_build_session_workflow`, `_PROFILE_STRATEGY`).
- `harness/workflows/registry.py` — `WORKFLOW_REGISTRY`, `get_workflow`, `list_workflows`.
- `harness/workflows/{simple_rag,crag,summarize_rag,react_native,composites,review}.py` — the workflows.
- `harness/workflows/utils.py` — `WorkflowRunner`, `load_system_prompt`, `_PROMPT_FILES`, helpers.
- `harness/prompts/system_*.md` — prompt variants.
- `harness/indexing/{registry,profiles,property_graph}.py` + `harness/configs/index/*.yaml` — retrieval axis.
- `docs/WORKFLOWS.md` (new, this pass) — the how-to.
