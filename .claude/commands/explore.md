---
description: Open a work unit from a docs/next proposal, and read the code and the stores before anything is planned
---

Open a work unit for one item from the backlog. First of four commands:
`/explore` → `/plan` → `/next` → `/ship`. See `docs/PLANNING_WORKFLOW.md`.

**Input**: `$ARGUMENTS` names a proposal in `docs/next/`, with or without the path and the
`.md` suffix. `eval_reliability`, `docs/next/eval_reliability.md` and `next/eval_reliability`
all mean the same file. When it is empty, list the proposals in the order `BACKLOG.md` gives
and stop.

## The rule that shapes this command

**The proposal is the requirements. Do not copy it.** `docs/next/<name>.md` already states what
would be built and how it would be checked. A `requirements.md` beside it would be a second
description of one task, and the two drift. The work unit **references** the proposal by path
and records only what the proposal does not: what the code, the installed libraries and the
stores actually look like today.

If the target is not in `docs/next/`, stop and say so. Offer to write the proposal first.

## Steps

1. **Resolve the target.** Find the proposal. If it does not exist, list what does and stop.
   If its row is not in `Now` of `BACKLOG.md`, say so and ask before going on: the backlog owns
   the order, and `Now` holds at most 3 rows.

2. **Create the work unit** at `.claude/work/YYYY-MM-DD_NN_<slug>/`, and write the unit id into
   `.claude/work/ACTIVE_WORK`. `NN` counts up across all units; the last unit before this
   workflow was 25. The unit holds:

   | File | Holds |
   |---|---|
   | `metadata.json` | `proposal` (the path), `backlog_row` (its number), `created_at`, `status` |
   | `exploration.md` | what the code, the libraries and the stores look like now, written by this command |
   | `state.json` | the task list, written by `/plan` |

   `metadata.json` names the proposal instead of copying it.

   **Make the unit's branch from `develop` first**, named by the unit's slug: `git switch -c
   <slug> develop`. Look before you switch: `git status` must list no change that another session
   left, and `git worktree list` no second checkout of that branch. A proposal's branch is never
   made from `main` (`docs/PLANNING_WORKFLOW.md`, "Branches").

3. **Mark the proposal as being worked on**, in the same sitting the unit opens. Three edits: the
   `**Status:**` line of `docs/next/<name>.md`, that proposal's row in `docs/next/README.md`, and
   the Notes cell of its row in `BACKLOG.md`. All three say the unit id and the date. A reader
   outside this session looks at those files, not at `.claude/work/`. Leave the *order* of the
   backlog alone: opening a unit does not change what should come next.

4. **Read the proposal, and check it against the code, the installed libraries and the stores.**
   A proposal can be older than the code. Verify every claim of absence ("there is no X",
   "nothing calls Y"), every claim about a third-party API, and every count. A count from
   MongoDB or Neo4j is checked with a read-only query, and the query goes into
   `exploration.md` beside its result. Record what is wrong and say whether the proposal still
   stands.

   A proposal here often leans on another repository. **Check those claims in that repository**,
   and record what the code there actually is:

   | Repository | What it is here |
   |---|---|
   | `~/github_repos/ema_scraper` | the crawler that fills the Scrapy cache and `web_items`. Its `parsers/` wrote the PDF pickles this repository still reads. A change there is that repository's work, with its own commit |
   | `~/github_repos/doctool` | the origin of this workflow. It holds Docling and PaddleOCR-VL parsing code (`src/dw/parsers/`) worth reading before a parser proposal |

5. **Explore the code the work would touch.** Name the files, the call sites and the tests that
   already cover them. Prefer `Grep` and `Read` over guessing. For a broad sweep, use the
   `Explore` agent.

6. **Check what this work has to preserve, and record it in `exploration.md`:**

   - **Source, derived and authored data.** Source is the Scrapy cache and `web_items`: this
     repository reads them and never rewrites them. Derived is `parsed_documents`,
     `document_metadata` and the Neo4j graph: a tool may rebuild them. Authored is
     `benchmark/*.jsonl`, the hub and routing YAML, the prompts and the recipes: no tool
     overwrites them. Say what the work writes, and which of the three kinds each place is.
   - **The live graph.** Does the work delete, rebuild or re-embed? Then say how many
     documents and chunks, how many hours on the one GPU, and whether the run can stop and
     resume. A full reset is the owner's decision, never a default.
   - **Comparable numbers.** Does it touch the benchmark items, the judge, the runner, the
     retriever's defaults or a recipe that earlier runs used? Then name the earlier numbers
     that stop being comparable, and the runs to repeat. And say whether the system under test
     can now read a gold answer: an index over `corpus.jsonl` leaked them once (`DECISIONS.md`).
   - **Cost.** Paid model calls and GPU hours, as an estimate with its arithmetic: items ×
     repeats × arms × calls per item.
   - **Scope.** The scope locks in `CLAUDE.md`, and the rule that a new layer answers a
     benchmark failure. The decision of 2026-11-23 in `DECISIONS.md` names the layers that the
     rehearsal admits.
   - **The public repository.** The plan this repository rehearses is private. A file here
     carries the plan's class and ladder labels (C1 to C9, E0 to E9) and public EMA content,
     and nothing else of it: no organisation, no person. A vendor and its public material
     may be named and cited.
   - **What it assumes that is not decided.** If the work only makes sense given a choice nobody
     has made, name that choice as an open question rather than settling it in code.

7. **Write `exploration.md`.** What exists, what the proposal got wrong, which files change,
   what could go wrong, and any question you could not answer from the code or the stores.
   Short sentences, one idea each, concrete numbers and versions rather than adjectives.

8. **Report** the unit path, whether the proposal still stands, and any open question. Then
   recommend `/plan`.

## What this command does not do

It writes no code and changes no store: every query it runs is read-only. The only files it
changes outside `.claude/work/` are the three status markers in step 3. It makes the unit's
branch and commits nothing on it unless the owner asks.

It does not decide priority. `BACKLOG.md` owns the order, and picking an item out of that order
is the owner's call, not this command's.
