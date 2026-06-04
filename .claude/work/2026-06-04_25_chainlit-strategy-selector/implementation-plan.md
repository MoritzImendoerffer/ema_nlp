# Implementation plan — Chainlit strategy selector (dynamic, registry-driven)

Work unit `2026-06-04_25_chainlit-strategy-selector`, Thread B. Basis: `requirements.md` Thread B +
`exploration.md` + the user directive (2026-06-04): *"select the desired configuration in the settings
panel, especially the workflow; **show the available options and if new strategies are available it should
pick them up.**"*

> **Supersedes** the earlier outline tasks TASK-002..005 (which assumed the hardcoded `_PROFILE_STRATEGY`
> list). The new requirement is **dynamic discovery** — the panel is built from the registries at runtime, so
> a newly-registered workflow / prompt file / index profile appears automatically with no app.py edit.

## 1. Overview & scope

Move workflow selection out of the pre-chat `cl.ChatProfile` and into the **live `cl.ChatSettings` panel**,
and make all option lists **registry-driven** so new strategies are picked up automatically:

- **Workflow** options ← `harness.workflows.registry.list_workflows()` (7 today).
- **Prompt strategy** options ← `_PROMPT_FILES` (3 today; needs a public accessor).
- **Index profile** options ← glob `harness/configs/index/*.yaml` (1 today: `neo4j_hier`).

Two layers:
- **Layer 1 (core, the user's primary ask):** dynamic **workflow + prompt_strategy** selectors, live-
  switchable mid-session. No index reload, no new infra beyond a tiny accessor + a builder-tolerance fix.
- **Layer 2 (retrieval axis, future-proofing):** a dynamic **index_profile** selector backed by a registry-
  level `open_index` dispatch (the RETRIEVAL_TRACKS §0.7 "P0"), so when Track A/B/C profiles land they show
  up and load correctly. For v1 it lists only `neo4j_hier`.

**In scope:** `app.py` (UI wiring), a `list_prompt_strategies()` accessor, builder-kwarg tolerance
(`harness/workflows/`), and the registry `open_index` dispatch (`harness/indexing/`). **Out of scope:** the
spec-only retrieval tracks themselves; reactive/conditional widgets; auth/history changes.

## 2. Verified facts the design rests on

- `Select` (chainlit 2.11.1) takes runtime `items: dict[value,label]` or `values: list[str]` + `initial_value`
  → **options are computed at `_make_chat_settings()` call time**. `ChatSettings(...).send()`/`.refresh()`
  emit `chat_settings`, so the panel can be (re)rendered mid-session; `on_settings_update(settings)` receives
  `{widget_id: value}`.
- `list_workflows()` → 7; `_PROMPT_FILES` keys → 3; profile glob → 1. All enumerable at runtime.
- **`get_workflow` forwards `prompt_strategy` only when non-None** (`registry.py:148`). `build_react_native`
  / `build_react_review` accept **no** `prompt_strategy`/`**kwargs` → passing one would `TypeError`. (Fixed by
  DL4.)
- **No registry `open_index` dispatch exists** — `app.py:_load_index_sync` hardcodes
  `property_graph.open_index` and reads `EMA_INDEX_PROFILE` as a module constant (lines 37, 239, 269). Profile
  switching needs both made profile-aware + a kind-dispatched opener (DL6).
- `_build_session_workflow(strategy, prompt_strategy, model_name, temperature, retrieval_k)` already exists —
  the workflow/prompt plumbing is one parameter away from done.

## 3. Locked design decisions

| # | Decision | Resolution (recommended) |
|---|----------|--------------------------|
| **DL1** | Option source | **Registry-driven at render time** — widgets built from `list_workflows()` / `list_prompt_strategies()` / profile glob. New entries auto-appear. This *is* the feature. |
| **DL2** | Workflow labels | Workflow `Select` uses `items={key: _WORKFLOW_LABELS.get(key, key.replace('_',' ').title())}` → known keys get friendly names, **unknown/new keys still render** (prettified). |
| **DL3** | One widget vs two | **Two**: a `workflow` Select (7) + a `prompt_strategy` Select (3). prompt_strategy always shown. |
| **DL4** | react + prompt_strategy crash | **Make all workflow builders tolerant of extra kwargs** (`**_: Any`) so a passed `prompt_strategy` is harmlessly ignored by `react`/`react_review` (and any future param-light strategy). Robust + future-proof; fixes the confirmed `TypeError`. |
| **DL5** | ChatProfile vs settings | **ChatProfile seeds** the initial widget values at chat-start; **settings is the live source of truth** thereafter (`on_settings_update` rebuilds). No double-control conflict. |
| **DL6** | Index-profile axis | **Include Layer 2**: add the registry `open_index` dispatch (P0) + profile-aware loading + a dynamic `index_profile` Select. Reload the index **only when the profile changes**. Separable if you want Layer 1 alone. |

## 3b. Review-driven amendments (adversarial pass — folded in)

A 2-agent review (plan-correctness = needs-revision, chainlit-runtime = solid) surfaced these; they amend
the tasks/touch-map below:

- **A1 — `EMA_INDEX_PROFILE` is read in 4 spots, not 2; two are at *invoke* time for tracing (BLOCKING).**
  Beyond `app.py:37/239/269`, it's read by `os.getenv` in `harness/workflows/utils.py:84` (`retriever_attributes`)
  and `:174` (`WorkflowRunner._stamp_span`). After an in-panel `index_profile` switch the rebuilt pipeline is
  correct, but those two reads still return the **startup** value, so the Phoenix `ema.index.profile` attr
  would report the OLD profile. **Fix (simplest):** in `on_chat_start` + the profile-change branch of
  `on_settings_update`, set `os.environ["EMA_INDEX_PROFILE"] = selected_profile` **before** rebuild (document
  the process-global side-effect). *(Note: `ema.orchestration.strategy`/`prompt_strategy` DO flip correctly —
  they come from each workflow's fresh `config_attributes()`. Only the profile attr needs this fix → it lives
  in the Layer-2 task CSEL-007.)*
- **A2 — CSEL-002 must NOT rename `property_graph.open_index` (BLOCKING).** It's imported directly by
  `app.py:235` and referenced in `harness/workflows/{simple_rag,crag,react_native,registry}.py`. **Fix:** keep
  `property_graph.open_index` named as-is and just add `@register_open("property_graph")` above it; the
  registry-level **dispatcher** `open_index(profile)` lives in `registry.py` (a different qualname — no clash)
  and is what `harness/indexing/__init__.py` re-exports. Add a regression test that
  `from harness.indexing.property_graph import open_index` still imports.
- **A3 — Auto-appear contract (the feature's true boundary).** "A new strategy auto-appears" holds only for
  builders callable from `(retriever, llm[, prompt_strategy])` alone. A registered builder that *requires* an
  extra non-defaulted kwarg would render in the Select but fail at `get_workflow` time. State this contract in
  DL2/CSEL-006. (Only `prompt_strategy` reaches the builder via `get_workflow`; `model_name`/`temperature`/
  `retrieval_k` go to `_build_session_workflow`, not the builder — make this explicit so `**_` isn't expected
  to swallow them.)
- **A4 — Guard the embed re-config on profile switch (GPU risk).** `_load_index_sync` calls
  `configure_embed_model()` which re-instantiates HuggingFace BGE on the 3090; repeated reloads risk the known
  GSP-crash-under-sustained-load. Since **all v1 profiles share the same embed model**, re-config the embed
  model **once per session** (or skip when the model name is unchanged), not on every profile switch. Folded
  into CSEL-007's reload guard.
- **A5 — Retain `_PROFILE_STRATEGY`.** It stays as the ChatProfile seed + the `on_chat_resume` thread-tag
  reverse-lookup (CSEL-005 relies on it). Only **2 builders** strictly need `**_` (`build_react_native`,
  `build_react_review`); the other 5 already accept `prompt_strategy` (adding `**_` to all is harmless
  uniformity).
- **A6 — Mid-session re-render resets ALL widget values to their inputs' `initial`.** Chainlit's
  `chat_settings` emit resets the whole client `ChatSettingsValue` atom from the new inputs. So
  `_make_chat_settings(current: dict)` **must seed `initial`/`initial_value` for *every* widget from
  `current`** (not just workflow/prompt/profile) or model/temp/k/cache snap back to defaults on any re-render.
  Prefer `.refresh()` over `.send()` for any mid-session re-render, and only re-render when a value the
  widget-set depends on changed. (The plan does NOT call `.send()` from `on_settings_update` today — safe; no
  re-emit loop, since `on_settings_update` only fires on the user's submit.)
- **A7 — A ChatProfile switch is a *full session reset*** (new websocket → fresh `on_chat_start`, empty
  `cl.user_session`), not a settings-only refresh. That is distinct from the in-panel `index_profile` Select
  (CSEL-007), which reloads the index within the live session. CSEL-005 already treats ChatProfile as a
  chat-start seed — keep that framing and note the distinction so the reload-on-change guard isn't misread.

## 4. Architecture — touch map

```
harness/workflows/utils.py      + list_prompt_strategies()  (public, over _PROMPT_FILES)
harness/workflows/react_native.py, composites.py   build_*() accept **_: Any   (DL4)
harness/indexing/registry.py    + OPEN_BUILDERS + register_open + open_index(profile)  (P0/DL6)
harness/indexing/property_graph.py   @register_open("property_graph") on existing open_index
harness/indexing/__init__.py    export open_index (registry dispatch; do NOT rename property_graph.open_index — A2)
harness/workflows/utils.py      reads EMA_INDEX_PROFILE at :84 (retriever_attributes) + :174 (_stamp_span) at
                                INVOKE time -> keep correct on profile switch via os.environ sync (A1)
app.py
  _WORKFLOW_LABELS / _WORKFLOW_DESCRIPTIONS         (friendly names; key-fallback)
  _chat_options() -> {workflows, prompt_strategies, index_profiles}   (pure; registry-driven)
  _make_chat_settings(current)                      dynamic workflow/prompt/profile Selects + model/temp/k/cache
  _settings_to_pipeline_kwargs(settings)            + workflow->strategy, prompt_strategy, index_profile
  _load_index_sync(profile_name)                    dispatch via registry open_index (not hardcoded)
  _build_session_workflow(index_profile=..., ...)   uses the chosen profile (not the module constant)
  on_chat_start / on_chat_resume                    seed widget initials from resolved ChatProfile + profile
  on_settings_update(settings)                      read strategy/prompt/profile; reload index iff profile changed; rebuild; update session
```

## 5. Task execution plan

Critical path **CSEL-001/002 → 003 → 004 → 005 → 006** (~9h). CSEL-001 and CSEL-002 are independent
foundations (parallelizable).

### CSEL-001 — Enabling harness changes: prompt-strategy accessor + builder kwarg tolerance *(foundation, ~1.5h)*
- Add `list_prompt_strategies()` (and `PROMPT_STRATEGIES` tuple) to `harness/workflows/utils.py` (or
  `registry.py`) over `_PROMPT_FILES`.
- **DL4:** add `**_: Any` to `build_react_native` and `build_react_review` (and, for uniformity, every
  `build_*`) so a forwarded `prompt_strategy` never raises.
- **Tests:** `list_prompt_strategies() == list(_PROMPT_FILES)`; `get_workflow("react", retriever=fake,
  llm=fake, prompt_strategy="cot_self")` does **not** raise and returns a runner.
- **Acceptance:** any workflow can be built with any `prompt_strategy` without error; accessor matches the files.

### CSEL-002 — Registry-level `open_index` dispatch (P0) *(foundation, ~1h, parallel)*
- `harness/indexing/registry.py`: `OPEN_BUILDERS` dict + `@register_open(kind)` + `open_index(profile, **kw)`
  dispatching on `profile.index.kind` (NotImplementedError listing registered kinds, mirroring
  `build_index`). `harness/indexing/property_graph.py`: decorate the existing `open_index` with
  `@register_open("property_graph")` (rename the module fn if needed to avoid the export clash). Export
  `open_index` from `harness/indexing/__init__.py`.
- **Tests** (mirror `test_indexing_profiles.py` registry tests): register a fake opener → dispatch hits it;
  unknown kind → `NotImplementedError`; `property_graph` registered after `import harness.indexing`.
- **Acceptance:** `from harness.indexing import open_index; open_index(profile)` works for `property_graph`
  and dispatches on kind. (Unblocks the index_profile axis + Track A/C later.)

### CSEL-003 — Dynamic ChatSettings panel *(feature, ~2h)*
- `_chat_options()` pure helper returns `{"workflows": list_workflows(), "prompt_strategies":
  list_prompt_strategies(), "index_profiles": [p.stem for p in profile_dir.glob("*.yaml")]}`.
- `_make_chat_settings(current: dict)` builds: `Select("workflow", items={k:_label(k)},
  initial_value=current["workflow"])`, `Select("prompt_strategy", items={p:p},
  initial_value=current["prompt_strategy"])`, `Select("index_profile", items={p:p},
  initial_value=current["index_profile"])`, then the existing model/temperature/retrieval_k/cache widgets.
- `_WORKFLOW_LABELS`/`_WORKFLOW_DESCRIPTIONS` for known keys; `_label(k)` falls back to a prettified key.
- **Tests:** `_chat_options()["workflows"] == set(list_workflows())` (locks "picks up new strategies");
  a monkeypatched extra registry entry appears in the options; `_make_chat_settings(...)` returns widgets with
  the expected ids/initials.
- **Acceptance:** the panel renders workflow + prompt + profile Selects whose values come from the registries;
  a hypothetical new registry entry would appear with no app.py edit.

### CSEL-004 — Thread the selection into the live rebuild *(feature, ~2h)* — deps CSEL-001, 002, 003
- `_settings_to_pipeline_kwargs(settings)` → `{"strategy": settings["workflow"], "prompt_strategy":
  settings["prompt_strategy"], "index_profile": settings["index_profile"], "model_name":…, "temperature":…,
  "retrieval_k":…}`.
- `_build_session_workflow(index, *, index_profile, strategy, prompt_strategy, …)` uses `index_profile`
  (not the module constant) for `load_index_profile`.
- `_load_index_sync(profile_name)` opens via the registry `open_index` (CSEL-002).
- `on_settings_update`: read strategy/prompt/profile from `settings`; **if `index_profile` changed** vs the
  session's, `await asyncio.to_thread(_load_index_sync, new_profile)` and store it (show a brief "reloading
  index…" message); rebuild the pipeline; update `cl.user_session` strategy/prompt/profile/index/settings.
- **Acceptance:** changing the workflow in the panel makes the next answer use it (Phoenix
  `ema.orchestration.strategy` flips; CRAG grade/rewrite steps appear); changing `index_profile` reloads the
  index; `react`/`react_review` run unaffected by the prompt setting; model/temp/k/cache unchanged.

### CSEL-005 — Seeding + ChatProfile reconciliation (DL5) *(feature, ~1h)* — deps CSEL-003
- `_DEFAULT_SETTINGS` becomes a function/seed built from the resolved ChatProfile `(strategy,
  prompt_strategy)` + the active `EMA_INDEX_PROFILE`. `on_chat_start` / `on_chat_resume` compute the seed and
  pass it to `_make_chat_settings(seed)` so the panel opens showing the active workflow. Settings is the live
  source of truth afterward.
- **Acceptance:** the panel's initial workflow/prompt/profile match the chosen ChatProfile; on resume they
  match the thread's tagged profile; no divergence between the ChatProfile and the panel at start.

### CSEL-006 — Tests + live verification + docs *(testing/docs, ~1.5h)* — deps all
- Unit tests (pure helpers, no Chainlit runtime): `_chat_options`, `_settings_to_pipeline_kwargs`, the
  registry `open_index` dispatch, builder tolerance. (app.py handlers themselves stay manually-verified.)
- **Live click-through:** switch workflow (CRAG steps + Phoenix attr), switch index_profile (reload), toggle
  model/temp/k/cache — all mid-session. `pytest` (workflow-registry + indexing suites) green; `ruff`/`mypy`.
- Docs: `app.py` module docstring (workflow now settings-selectable + dynamic); one line in `chainlit.md` /
  `docs/WORKFLOWS.md` that the panel auto-lists registered strategies.

## 6. Quality assurance

- **Offline-testable core:** the option-enumeration + kwarg-mapping + registry-open dispatch are pure and
  unit-tested; the "new strategy auto-appears" property is locked by a monkeypatch test (register a fake
  workflow → assert it shows in `_chat_options()`).
- **The react/prompt crash is regression-tested** (CSEL-001) — the single highest-risk behavior.
- **Chainlit handlers** (`on_settings_update`, `on_chat_start`) are verified live (Chainlit has no headless
  harness here); keep all logic in pure helpers so the handlers are thin.
- Gates per task: `pytest tests/`, `ruff check .`, `mypy` on touched modules.

## 7. Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| Passing `prompt_strategy` to `react`/`react_review` → `TypeError` (confirmed) | DL4: builders accept `**_`; CSEL-001 regression test. |
| Profile switch needs index reload (slow: Neo4j + BGE ~seconds) | Reload only when `index_profile` actually changed; `asyncio.to_thread` + a "reloading…" message. |
| Non-`property_graph` profile can't be opened (no P0) | CSEL-002 adds the dispatch; v1 lists only `property_graph` profiles, future kinds register their opener. |
| Chainlit can't hide prompt_strategy for react reactively | Always show it; ignored where N/A (documented). Conditional widgets deferred (open question). |
| `EMA_INDEX_PROFILE` read in 2 module-level spots | CSEL-004 threads the chosen profile through both `_load_index_sync` and `_build_session_workflow`. |

## 8. Estimate & sequencing

~**9 h**. Foundations CSEL-001 (1.5h) ∥ CSEL-002 (1h) → CSEL-003 (2h) → CSEL-004 (2h) → CSEL-005 (1h) →
CSEL-006 (1.5h). Layer 1 (001,003,004 partial,005) is shippable without Layer 2 (002,006 profile bits) if
you want the workflow selector first.

## Open questions

1. **Conditional prompt widget** — hide `prompt_strategy` when the selected workflow ignores it (react)?
   Needs a `refresh()` on workflow-change; deferred (always-show + ignore is simpler and correct).
2. **Dynamic ChatProfile** — also generate the pre-chat `cl.ChatProfile` list from `list_workflows()` (vs the
   current 9-flat seed)? Or simplify to a single "default" profile now that the panel owns selection? Defer.
3. **Index-reload UX** — a few seconds on profile change; is a transient message enough, or stream progress?
