# Database sync across machines — requirements

## User intent (verbatim)

> I want to be able to effortlessly synchronize the work with different machines.
> Git already covers the code. Nextcloud the data. I need a way to synchronize
> also the databases. There is already a script for exporting and importing the
> mongo database. Is there a similar way for the postgres database available?
> Explore good options present me your findings. I want: a single script that
> dumps everything to my nextcloud so that I can seamlessly transition to my
> laptop or to other machines.

## Today's state (what already works)

- `scripts/sync_mongo.sh export|import|pull` — handles the Mongo half via
  `mongodump --archive` → `~/Nextcloud/Datasets/mongo_sync/ema_scraper.archive`,
  with a confirm-before-drop and an optional SSH-live `pull` mode.
- `corpus/`, `harness/`, `tests/` are git-tracked; `.claude/work/` too. Code is
  fully covered by `git pull`.
- `~/Nextcloud/Datasets/ema_nlp/{corpus, index, results}` already syncs corpus
  artefacts + FAISS query cache + eval results (REFACT-019). The narrative
  Postgres store is the only major asset NOT in either of these channels.

## Today's gap

There is no equivalent for the Postgres `ema_nlp` database. Effects:
- On a fresh machine, the only way to get `documents`/`chunks`/`links` is to
  re-run `harness.embed_pg` from Mongo, which requires re-embedding
  ~71k pending docs (≈10–40 hours on this laptop's CPU).
- The expensive artefact — the embeddings — is not transferable.

## In scope

1. A way to dump the `ema_nlp` Postgres DB to a file on Nextcloud, restore it
   on another machine, and have everything (schema, data, pgvector embeddings,
   HNSW + GIN + tsvector indexes) come back intact.
2. A single entry-point script that dumps **both** databases (Mongo + Postgres)
   to Nextcloud, and a symmetric one-shot import on the destination.
3. Symmetric ergonomics with the existing `sync_mongo.sh`: same flags, same
   confirm-before-drop pattern, same env-var configuration.
4. A manifest sitting next to the archives so the receiver can sanity-check
   timestamps, source machine, and counts before destroying their local DB.

## Out of scope (v1)

- Two-way merge / conflict resolution. Sync is last-writer-wins per machine;
  the user picks which side is canonical at import time.
- Automated/scheduled sync. Manual `export` + manual `import` only.
- Incremental / delta sync of vectors (overkill; the embedding sweep happens
  rarely, and full custom-format dumps are fast enough at current sizes).
- Cloud-backup style retention. The script writes one current archive and
  overwrites it on next export (same as `sync_mongo.sh` does today).
- The FAISS `query_cache.faiss` already lives under
  `~/Nextcloud/Datasets/ema_nlp/index/` and needs no extra handling.

## Functional requirements

| ID    | Requirement |
|-------|-------------|
| FR-1  | A `sync_pg.sh export` subcommand that dumps the `ema_nlp` Postgres DB to `~/Nextcloud/Datasets/db_sync/pg.dump` (or analogous path) via `pg_dump --format=custom -Z 6` running inside the `ema_nlp_pg` container, so the host needs no `pg_dump` install. |
| FR-2  | A `sync_pg.sh import` subcommand that restores from that archive via `pg_restore --clean --if-exists --no-owner --no-privileges`, with a `[!]` confirmation prompt identical in tone to the existing mongo script. |
| FR-3  | A `sync_pg.sh pull --host X` subcommand mirroring the mongo SSH live-pull, piping `pg_dump` over SSH directly into a local `pg_restore` (Tailscale-friendly). |
| FR-4  | A unified `sync_databases.sh {export\|import\|status}` wrapper that dispatches to `sync_mongo.sh` + `sync_pg.sh` in sequence, writes a `manifest.json` alongside the archives, and shows a single combined summary at the end. |
| FR-5  | `manifest.json` records per-DB: source hostname, archive UTC timestamp, archive bytes, sha256 checksum, and a key count (Mongo `web_items` count, Postgres `chunks` count). |
| FR-6  | `import` reads `manifest.json` first, refuses to proceed if a checksum mismatches (catches Nextcloud-in-flight uploads), and prints the source hostname + age before the destructive prompt. |
| FR-7  | A `--only mongo` / `--only pg` flag on the wrapper for partial sync. |
| FR-8  | All scripts respect the existing env-var conventions: `NEXTCLOUD_DATASETS`, `MONGO_URI`, plus new `POSTGRES_USER`, `POSTGRES_DB`, `PG_PORT` (already declared in `deploy/postgres/docker-compose.yml`). |
| FR-9  | All scripts work from a clean clone with only Docker + `mongodb-database-tools` (host) installed — no PG client required because we exec inside the container. |
| FR-10 | One-line documentation update in `docs/SETUP.md` (or new `docs/SYNC.md`) explaining the round-trip and the “export → wait for Nextcloud → import” cadence. |

## Non-functional requirements

- **Reliability.** Export must be atomic from the receiver's view: write to a
  `.partial` file first, `mv` to the final name only after success; `manifest.json`
  written last. Import verifies sha256 before touching the live DB.
- **Performance.** Single export of the full state should complete in under
  10 minutes on either machine. Restore on a fresh DB should not exceed
  30 minutes after the full embedding sweep is in place (most of that is
  HNSW index rebuild).
- **Safety.** Destructive subcommands always print the source hostname,
  archive timestamp, and local count, then prompt `[y/N]` (default no).
- **Footprint.** Combined archive ≤ 10 GB after the full embedding sweep
  (estimate: ~3 GB Mongo + ~3–5 GB Postgres custom-format). Stays inside
  Nextcloud's comfortable single-file size band.
- **Version tolerance.** Both DBs are version-pinned via Docker, so the
  archives don't need to survive engine upgrades; we use logical (not
  physical) dumps anyway, which gives us margin for a major-version bump
  later without breaking historical archives.

## Acceptance criteria

1. From a fresh `git clone` on a third machine with only Docker + the dump
   tools installed: `bash scripts/sync_databases.sh import` reconstructs both
   DBs with byte-identical counts (within a tolerance for non-deterministic
   `parsed_at` timestamps).
2. Round-trip export → import on the same machine is a no-op in effect
   (same counts, same chunk hashes, same retrieval results from a fixed
   seed query against `harness.retrieve_pg`).
3. A deliberately corrupted archive (truncated file, mismatched sha256) is
   rejected at `import` time with a clear error, before any DROP runs.
4. Existing `sync_mongo.sh` continues to work unchanged for users who want
   only the Mongo half.
5. `docs/SETUP.md` (or new `docs/SYNC.md`) has a “New machine bootstrap”
   recipe ending in `sync_databases.sh import`.

## Risks & open questions

- **HNSW rebuild cost on restore.** `pg_dump` custom format includes the
  `CREATE INDEX … USING hnsw` statement; restore rebuilds the index from
  scratch. For 42k chunks (current marvin-gpu state) this is ~1–3 min.
  After the pending sweep (~700k chunks) it becomes 20–40 min. Acceptable,
  but worth surfacing in docs.
- **Nextcloud upload time.** A 5 GB archive over a typical home upstream
  is ~30–90 min. Document this so the user doesn't try to import on the
  laptop before the upload from marvin-gpu has finished.
- **Concurrent writes during dump.** Both `mongodump` and `pg_dump` use
  consistent snapshots, so a running sync against either DB doesn't corrupt
  the archive — but the snapshot won't include writes that arrive mid-dump.
  Practical impact for a solo dev: negligible.
- **The "last-writer-wins" model.** If the user works on the laptop and on
  marvin-gpu without exporting in between, one side's changes will be lost
  on next import. The script should print a strongly-worded warning when
  the local DB has been modified more recently than the incoming archive
  (compare a `documents.ingested_at MAX()` against the archive's manifest
  timestamp). This is the most likely accidental-data-loss vector.
- **PG client not on host.** Avoid by running `pg_dump`/`pg_restore` inside
  the `ema_nlp_pg` container via `docker exec`. This matches what
  `start_services.sh` already does.

## Decisions locked (2026-05-30)

1. **Archive layout**: consolidated under `~/Nextcloud/Datasets/db_sync/`.
   One-time migration of the existing mongo archive
   (`~/Nextcloud/Datasets/mongo_sync/ema_scraper.archive` →
   `~/Nextcloud/Datasets/db_sync/mongo.archive.gz`).
2. **Wrapper ownership**: `sync_databases.sh` shells out to `sync_mongo.sh`
   and `sync_pg.sh`. Both per-DB scripts gain a `--yes` flag so the wrapper
   can suppress the per-script confirmation and run a single combined
   confirmation instead.
3. **`--no-embeddings` flag**: yes, on `sync_pg.sh` and passed through from
   `sync_databases.sh`. Excludes `chunks` table data; documents+links still
   round-trip. Receiver rebuilds chunks via `harness.embed_pg` when needed.
4. **Storage backend**: Nextcloud today, but accessed through a thin
   `_put_artifact`/`_get_artifact`/`_list_artifacts` shell-function layer
   so a future swap to MinIO/B2/S3 is a config flag, not a rewrite.

## Functional requirements — addendum from locked decisions

| ID    | Requirement |
|-------|-------------|
| FR-11 | A shared bash helper (`scripts/lib/_artifact_store.sh`) defining `_put_artifact`/`_get_artifact`/`_list_artifacts`/`_stat_artifact`, parameterised by `STORAGE_BACKEND` env var (default: `nextcloud`). Today only `nextcloud` is implemented; the dispatch hook is in place for future `minio` / `s3` / `b2` backends. |
| FR-12 | Both `sync_mongo.sh` and `sync_pg.sh` accept a `--yes` flag that suppresses the confirm-before-drop prompt (for wrapper use). When `--yes` is set, the script still prints what it's about to do, just without the read prompt. |
| FR-13 | Migration step on first `sync_databases.sh export`: detect the legacy `~/Nextcloud/Datasets/mongo_sync/ema_scraper.archive` and move it to `~/Nextcloud/Datasets/db_sync/mongo.archive.gz` (re-compressing in flight). Leave a symlink at the old path for one transition cycle, with a deprecation note printed. |
