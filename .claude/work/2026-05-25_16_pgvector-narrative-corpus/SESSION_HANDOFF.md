# Session handoff — NARR-001..009 complete, NARR-010 next

Last session ran NARR-001 through NARR-009 on `marvin-gpu` (the 3090 PC).
The two-machine split documented in `decisions.md` §2 is **no longer
applicable** — `marvin-gpu` has the GPU **and** a local MongoDB with the
ema_scraper data, so all remaining tasks execute on this single host.

## What's in place

- **Postgres**: `pgvector/pgvector:pg16` container `ema_nlp_pg`, started by
  `deploy/postgres/docker-compose.yml`. Volume `ema_nlp_pgdata`. pgvector
  extension 0.8.2.
- **Env file**: `~/.myenvs/ema_nlp.env` exists with `PG_DSN`, `MONGO_URI`,
  `EMA_RETRIEVER=faiss` (still legacy default), and the upstream-synced
  ANTHROPIC / GITHUB / chainlit secrets.
- **Schema**: `corpus/pg_schema.sql` applied; `documents`, `chunks`, `links`
  with HNSW + GIN. Idempotent re-runs verified.
- **Ingest**: `harness.embed_pg.ingest_source('pdfs', …)` works on real
  data — a `--limit 10` run produced 10 docs + 311 chunks in ~10s.
  `scripts/test_ingest_resume.py` proves resume + `--force` semantics.
- **HTML normaliser**: `corpus.ingestion.html_normaliser.normalise_html`
  + `normalise_html_doc`. Trafilatura with `favor_recall=True`. Landing
  pages (<200 chars) return None.

Current data already in PG after the smoke runs:
- `documents`: 15 rows (10 from `--limit 10`, 5 from `--limit 5`)
- `chunks`: 361 rows
- `links`: 0 (NARR-012+ not started)

## Next task: NARR-010 — extend ingest pipeline to HTML source

The HTML normaliser exists; what NARR-010 needs is:

1. **Verify the dispatcher already wired in `embed_pg.py` actually works
   for `--source html`.** I lazy-imported `normalise_html_doc` inside
   `_prepare_html` to avoid blocking NARR-007 on NARR-009. With NARR-009
   landed, that import will resolve. Run:
   ```bash
   .venv/bin/python -m harness.embed_pg --source html --limit 10 --batch-size 4
   ```
   then verify in psql:
   ```sql
   SELECT source_type, COUNT(*) FROM documents GROUP BY source_type;
   ```
2. Skipped landing pages must be logged with URL + reason. Today they
   silently return None — add a single info log in the loop:
   `_log.info("skipped html: %s (landing or extraction empty)", url)`.
   Either inside `_prepare_html` or in the main ingest loop (preferred,
   so the log point is symmetric with PDF normalise failures).
3. AC quote: *"Limit-10 dry run produces documents with source_type='html'
   in Postgres"*. Easy to verify once #1 lands.

After NARR-010, the remaining critical path is:

```
NARR-011 timing notes (10-100 PDF + HTML)
NARR-012 link_extractor module          ─┐
NARR-013 wire link extraction into ingest │ Phase D
NARR-014 resolve_links.py                ─┘
NARR-015 RetrievalConfigPG + adapter     ─┐
NARR-016 dense retrieval                  │
NARR-017 BM25 retrieval                   │ Phase E
NARR-018 hybrid + build_retrieve_fn_pg    │
NARR-019 auto traversal                   │
NARR-020 follow_links FunctionTool       ─┘
NARR-021 EMA_RETRIEVER dispatch in app.py ─┐
NARR-022 same in run_eval.py + Phoenix attr│ Phase F
NARR-023 simple_rag E2E smoke            ─┘
NARR-024 YAML prefilter/traversal exposure
NARR-025 unit test suite                 ─┐
NARR-026 retrieve_pg integration test     │ Phase H
NARR-027 docs (CLAUDE + RETRIEVAL_PG)     │
NARR-028 flip EMA_RETRIEVER default      ─┘
```

## Re-entry checklist for the next session

```bash
# 1. Make sure the PG container is up
cd ~/github_repos/ema_nlp/deploy/postgres
docker compose ps        # expect ema_nlp_pg running
docker compose up -d     # if it isn't

# 2. Sanity-check the venv (chowned to user this session — see HISTORY)
ls -la .venv | head -3   # should be moritz:moritz

# 3. Continue with NARR-010
/workflow:next  # or /next, depending on installed skills
```

The TaskList ID 10 (`NARR-010`) is the next claim. `state.json` already
reflects `current_task = "NARR-010"` and `next_available =
["NARR-010", "NARR-012", "NARR-015"]` (the three off-path branches that
can start in parallel after Phase B+C foundations are in).

## Gotchas to remember

- **Venv ownership**: `.venv/` was created as root in an earlier session.
  This session chown'd it to `moritz:moritz`. If `pip install` ever errors
  with `Permission denied` again, that's the same drift — chown again.
- **uv vs pip**: This venv has no `pip` installed; use
  `uv pip install --python .venv/bin/python …` for any new deps.
- **trafilatura's `favor_recall=True`** keeps borderline navigation pages
  alive (homepage produced 1.4k chars). If the corpus shows too much nav
  noise after the full HTML ingest, tighten `_MIN_TEXT_CHARS` in
  `html_normaliser.py` or set `favor_recall=False`.
- **Mongo `content_type: 'text/html'`** works as an equality match
  against the 1-element list field — confirmed (22,743 docs).
- **`harness.pg` package**: `conn.get_pool()` is a process-singleton.
  Tests that need a different DSN must call `close_pool()` first or
  inject their own pool.
