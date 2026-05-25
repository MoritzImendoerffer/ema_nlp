# Requirements: Chat UI Enhancements

**Work unit:** `2026-05-25_13_chat-ui-enhancements`
**Source:** Exploration conversation 2026-05-25

---

## Functional requirements

### FR-1 · Chat history sidebar (left)
- Thread list shown in Chainlit's left sidebar across page reloads
- Each thread shows its title (first question) and timestamp
- Clicking a thread resumes it — pipeline reloads with the correct workflow strategy
- Backed by SQLite (local file, no server); auth via env-var password

### FR-2 · Model and parameter controls (right panel)
- Settings panel floated to the right sidebar (Chainlit `chat_settings_location = "sidebar"`)
- Controls: agent model (dropdown from `models.yaml`), temperature (0–1 slider), retrieval k (3–20 slider), cache enabled (toggle)
- Changes take effect on the next query (pipeline rebuilt with new settings)
- Default values mirror current hardcoded values in `app.py`

### FR-3 · Workflow profile selector
- Chainlit `ChatProfile` dropdown at new-chat time
- One profile per strategy in `WORKFLOW_REGISTRY` (9 entries)
- Profile name → strategy key via a plain dict in `app.py`; no YAML involved
- Selected profile shown in session header throughout the conversation

---

## Non-functional requirements

- `aiosqlite` only new dep (added to `[ui]` extras)
- Auth password loaded from env var `UI_PASSWORD`; falls back to `"dev"` for local use
- `chat_history.db` must be `.gitignore`d
- App stays in a single file (`app.py`); no new modules
- All existing functionality (Phoenix tracing, 👍/👎, cache lookup) must continue to work
- Ruff + mypy clean

---

## Out of scope
- Multi-user auth (OAuth, LDAP)
- Per-profile retrieval k or model overrides (profile → strategy string only)
- YAML-based profile configuration
