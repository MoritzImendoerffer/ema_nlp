---
type: pm-decision
epic: 2026-11-23_26_eval-reliability
status: settled
settled: 2026-11-23
opened: 2026-11-23
blocks: TASK-015
tags: [pm/decision]
---

# The new API key is not scoped to a workspace

Written by Claude (Opus 5.5) during `/next` on 2026-11-23, after the owner updated
`ANTHROPIC_API_KEY` in the credentials file for the live run of TASK-015.

## What happened

Before the paid run, the free model listing (`GET /v1/models`, no model call) was made with
the new key. It returned:

```
400 invalid_request_error: This API key is not scoped to a workspace, so this request must
include the anthropic-workspace-id header with the ID of the workspace to use. Add the
header, or use an API key that is scoped to a workspace.
```

No model was called and no store was written. The live run did not start.

## Why it cannot be worked around inside TASK-015

Every request of the run would need the header `anthropic-workspace-id`. Three code paths
send requests, and none sets it:

- the agent's model, built by `harness/llms.py` (`_make_anthropic`, LlamaIndex `Anthropic`);
- `harness/models.py` (`_call_anthropic`);
- the mlflow judges (`harness/eval/judges.py` → mlflow's gateway adapter).

The installed `anthropic` SDK 0.105.2 has no setting that adds the header for an API key
(`anthropic/_client.py` names no workspace). Adding the header in the three paths is new
code that the proposal does not ask for.

## The options

| | What | What it costs |
|---|---|---|
| **(a)** | Replace the key with one created inside a workspace (Claude Console → the workspace → API keys) | No code change. The run starts as planned |
| **(b)** | Add a setting, e.g. `ANTHROPIC_WORKSPACE_ID`, that the three paths send as the header | New code in three files plus tests; a backlog row and a proposal first (`CLAUDE.md`, rule 1) |

## Recommendation

**(a).** It is a change of one line in the credentials file and keeps the run exactly as the
decision note `2026-11-23_live-check-run.md` settled it.

## The answers

**2026-11-23, the owner: the key's scope is "Organization".** This confirms the cause: a key
of organization scope belongs to no workspace, so the API asks each request to name one.
The choice between (a) and (b) is still open.

**2026-11-23, the owner: "I want option b. I have free credits on this key."** The repository
reads `ANTHROPIC_WORKSPACE_ID` from the credentials file and sends it as the header
`anthropic-workspace-id` on every Anthropic request: the agent's model, `harness/models.py`
and the mlflow judges. Built as TASK-016 of this unit; TASK-015 depends on it. The owner adds
the workspace ID to the credentials file.
