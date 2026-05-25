# Implementation Plan: Chat UI Enhancements

## Overview

Three independent Chainlit 2.11 features added to `app.py` and `.chainlit/config.toml`. No new modules; no new external services. The only new package dependency is `aiosqlite` (SQLite async driver for chat persistence).

Execution order chosen to deliver visible value earliest and front-load the simplest work:

```
TASK-001 (profiles)  ←── no deps, simplest, most visible
TASK-002 (settings)  ←── no deps
TASK-003 (history)   ←── no deps, most infra work
TASK-004 (resume)    ←── depends on TASK-003
```

---

## Task execution plan

### TASK-001 · Workflow profile selector  
**Type:** Feature · **Estimate:** 1.5 h · **Priority:** high · **Deps:** none

Add a `ChatProfile` dropdown so users can select the LlamaIndex workflow strategy at the start of each new thread. Replaces the `EMA_WORKFLOW_STRATEGY` env var for interactive use (env var still honoured as the default when no profile is selected).

**Changes:**
- `app.py`: add `_PROFILE_STRATEGY` dict (display name → registry key), add `@cl.set_chat_profiles`, update `on_chat_start` to read `cl.user_session.get("chat_profile")`
- Remove the module-level `WORKFLOW_STRATEGY` fallback (or keep as default if profile is `None`)

**Acceptance criteria:**
- [ ] Profile dropdown appears before first message in a new thread
- [ ] Selecting "CRAG" causes CRAG pipeline to be built (log `strategy=crag`)
- [ ] Selecting "Simple RAG" uses `simple_rag_zero`
- [ ] All 9 strategies listed and selectable
- [ ] `EMA_WORKFLOW_STRATEGY` env var still sets the default profile

---

### TASK-002 · Model and parameter settings panel
**Type:** Feature · **Estimate:** 2.5 h · **Priority:** high · **Deps:** none

Add a right-sidebar settings panel with controls for agent model, temperature, retrieval k, and cache toggle. Changes take effect on the next query.

**Changes:**
- `.chainlit/config.toml`: set `chat_settings_location = "sidebar"`
- `app.py`:
  - In `on_chat_start`, send `ChatSettings([Select(model), Slider(temp), Slider(k), Switch(cache)])`
  - Model choices read from `list(models.yaml models: keys)` — either hardcoded list or dynamically loaded from `harness/configs/models.yaml`
  - Add `@cl.on_settings_update(settings)` to store settings in `cl.user_session` and rebuild pipeline
  - Modify `_build_session_workflow` to accept `model_name`, `temperature`, `retrieval_k` overrides
  - Default values: model=`claude_opus`, temperature=`0.0`, k=`10`, cache=`True`

**Acceptance criteria:**
- [ ] Settings panel visible in right sidebar after chat loads
- [ ] Changing model select and submitting a query uses new model (check log)
- [ ] Changing k slider changes `RetrievalConfig.k` for next query
- [ ] Disabling cache prevents cache lookup on next query
- [ ] Defaults match current hardcoded values

---

### TASK-003 · SQLite chat history persistence + auth
**Type:** Integration · **Estimate:** 2.5 h · **Priority:** medium · **Deps:** none

Wire Chainlit's `SQLAlchemyDataLayer` with a local SQLite file so threads persist across page reloads and appear in the left sidebar. Adds a minimal password-auth callback so the data layer has a user identity to associate threads with.

**Changes:**
- `pyproject.toml`: add `aiosqlite>=0.20` to `[ui]` extras
- `.gitignore`: add `chat_history.db`
- `app.py`:
  - Add `@cl.password_auth_callback` — reads `UI_PASSWORD` env var; accepts any username with that password; returns `cl.User(identifier=username)`
  - Add `@cl.data_layer` returning `SQLAlchemyDataLayer("sqlite+aiosqlite:///chat_history.db")`
  - Store workflow strategy in thread metadata on chat start so resume can recreate the pipeline
- `.chainlit/config.toml`: no auth-specific changes needed (auth enabled automatically when `password_auth_callback` is registered)

**Acceptance criteria:**
- [ ] Login prompt appears on first visit; `UI_PASSWORD=dev` (or env default) grants access
- [ ] After answering a question, thread appears in left sidebar
- [ ] Restarting `chainlit run app.py` and refreshing browser shows prior threads
- [ ] `chat_history.db` file created in project root; `.gitignore`d
- [ ] Phoenix tracing and 👍/👎 feedback continue to work

---

### TASK-004 · Thread resume handler
**Type:** Feature · **Estimate:** 1 h · **Priority:** medium · **Deps:** TASK-003

Add `@cl.on_chat_resume` so clicking a thread in the sidebar recreates the pipeline with the correct workflow strategy, without re-embedding the index.

**Changes:**
- `app.py`: add `@cl.on_chat_resume(thread: dict)` that reads `thread["metadata"]["strategy"]`, rebuilds pipeline (reuses already-loaded index from session or reloads), restores `msg_counter` from thread step count

**Acceptance criteria:**
- [ ] Clicking a prior thread in sidebar resumes without "Loading index…" (index already in memory) — or loads it if server was restarted
- [ ] `pipeline` and `cache` session vars are set correctly after resume
- [ ] Subsequent queries in the resumed thread work normally

---

## Quality assurance

No new test files needed — these are UI-layer changes with no extractable pure logic. Manual verification suffices:
- Run `chainlit run app.py`, log in, send a question, reload page, verify thread persists
- Verify settings change propagates to pipeline (log output)
- Verify all 9 profiles are selectable and map correctly

Ruff and mypy must pass before marking complete.
