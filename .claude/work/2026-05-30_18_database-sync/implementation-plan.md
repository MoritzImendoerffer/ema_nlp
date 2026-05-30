# Database sync — implementation plan

Work unit: `2026-05-30_18_database-sync`
Status: `planning_complete` — ready for `/next`

## Overview

Add a single-script cross-machine sync for both the Mongo `ema_scraper` and the
Postgres `ema_nlp` databases, on top of the existing `sync_mongo.sh` foundation.
The user types `sync_databases.sh export` on one machine and
`sync_databases.sh import` on another; Nextcloud is the transport in between.

Locked design decisions (see `requirements.md`):
- Archives consolidate under `~/Nextcloud/Datasets/db_sync/`.
- Wrapper shells out to per-DB scripts; both per-DB scripts gain `--yes`.
- `--no-embeddings` flag excludes the `chunks` table from PG dumps.
- Storage access goes through a thin abstraction layer so the Nextcloud backend
  can later swap for MinIO/B2/S3 with one env-var change.

## Technical architecture

```
scripts/
├── lib/
│   ├── _artifact_store.sh   NEW  Storage abstraction (Nextcloud today)
│   └── _manifest.sh         NEW  manifest.json writer/reader/verifier
├── sync_mongo.sh            EDIT gzip, sha256, --yes, new archive path
├── sync_pg.sh               NEW  Symmetric to sync_mongo.sh
└── sync_databases.sh        NEW  Unified wrapper (export/import/status)
```

```
~/Nextcloud/Datasets/db_sync/   (NEW — single archive directory)
├── manifest.json               combined manifest, written last on export
├── mongo.archive.gz            mongodump --archive --gzip output
└── pg.dump                     pg_dump --format=custom -Z 6 output
```

The PG dump runs **inside the `ema_nlp_pg` container** (`docker exec`), so the
host doesn't need a PG client install. Mongo continues to use the host-side
`mongodump` (already installed on both machines).

## Task execution plan

### Phase A — Foundations (4h, parallelisable)

Two reusable bash helpers that the per-DB scripts and the wrapper all source.

| Task | Hours | Depends on |
|---|---|---|
| DBSYNC-001 — `_artifact_store.sh` (put/get/list/stat with Nextcloud backend) | 2 | — |
| DBSYNC-002 — `_manifest.sh` (init/add_db/finalize/read/verify) | 2 | — |

These have no dependencies on each other; can be worked in parallel or in
either order. Both ship with `bats` unit tests under `tests/scripts/`.

### Phase B — Per-DB scripts (6h, parallelisable)

| Task | Hours | Depends on |
|---|---|---|
| DBSYNC-003 — `sync_pg.sh export + import` (no pull, no `--no-embeddings` yet) | 3 | DBSYNC-001, DBSYNC-002 |
| DBSYNC-004 — Extend `sync_mongo.sh` (gzip, sha256, `--yes`, new path + migration) | 3 | DBSYNC-001, DBSYNC-002 |

DBSYNC-003 stands up the Postgres twin of the existing Mongo script. DBSYNC-004
brings the existing Mongo script onto the shared helpers and the new archive
path. Both can proceed in parallel once Phase A is done.

### Phase C — Wrapper + flags (5h)

| Task | Hours | Depends on |
|---|---|---|
| DBSYNC-005 — `--no-embeddings` flag on `sync_pg.sh` | 2 | DBSYNC-003 |
| DBSYNC-006 — `sync_databases.sh` wrapper (export/import/status, `--only`) | 3 | DBSYNC-003, DBSYNC-004 |

DBSYNC-006 is the "single script" deliverable the user asked for. DBSYNC-005
adds the development-loop ergonomics flag.

### Phase D — Polish (4h, parallelisable)

| Task | Hours | Depends on |
|---|---|---|
| DBSYNC-007 — `sync_pg.sh pull` (SSH live mode, mirrors `sync_mongo.sh pull`) | 2 | DBSYNC-003 |
| DBSYNC-008 — Stale-overwrite guard in `sync_databases.sh import` | 2 | DBSYNC-006 |

DBSYNC-007 is the Tailscale-friendly direct-pipe path. DBSYNC-008 is the
single most important safety feature against accidental data loss when the user
forgets to export before switching machines.

### Phase E — Ship (4h)

| Task | Hours | Depends on |
|---|---|---|
| DBSYNC-009 — `docs/SYNC.md` operator's guide + cross-links | 2 | DBSYNC-006 |
| DBSYNC-010 — End-to-end smoke test on this laptop | 2 | DBSYNC-006, DBSYNC-009 |

## Critical path

`DBSYNC-001 → DBSYNC-003 → DBSYNC-006 → DBSYNC-009 → DBSYNC-010`
(≈ 12h serial; the rest can run alongside without extending wall-clock)

## Quality assurance strategy

**Testing**
- Each helper and per-DB script ships with a `bats` test under
  `tests/scripts/`. We don't have `bats` in the project yet; DBSYNC-001 adds it
  to the dev extras in `pyproject.toml` (or via `apt install bats-core` — TBD
  during DBSYNC-001 once we see what's available cleanly).
- Integration test (DBSYNC-010) runs the full round-trip against the live
  laptop databases. Acceptable because export is non-destructive and the
  laptop's PG is currently empty — round-trip can't lose data.
- The corrupted-archive test in DBSYNC-010 explicitly verifies the
  fail-before-DROP invariant — the single most important behavioural contract
  for cross-machine safety.

**Backward compatibility**
- `sync_mongo.sh` keeps working standalone with the existing CLI surface.
  Only additions: `--yes` flag, new archive path. Old archive path retains a
  symlink for one transition cycle.
- No changes to data schemas, application code, or `start_services.sh`.
- No changes to anything users have wired into their muscle memory besides
  the archive path (and that's transitioned via symlink).

**Operational safety**
- All destructive operations gated behind a confirm prompt (default: no);
  `--yes` only suppresses the prompt for wrapper use.
- sha256 verification happens BEFORE any DROP; corrupted archives cannot
  trigger data loss.
- The stale-overwrite guard (DBSYNC-008) requires typing the word `overwrite`
  to confirm — escalated from `[y/N]` for that specific scenario.
- Combined manifest written LAST on export; receivers can use its presence as
  the signal that the archive is complete.

**Performance budget** (validated against estimates in `exploration.md` §5)
- Export wall-clock target: ≤ 10 min on either machine post-sweep.
- Import wall-clock target: ≤ 30 min on a fresh machine post-sweep (HNSW
  rebuild dominates and is unavoidable for logical dumps).
- Nextcloud footprint: ≤ 7 GB post-sweep, ≤ 2 GB pre-sweep.

## Dependencies on existing systems

- `scripts/start_services.sh` must have run on the destination before import
  (creates PG container + applies schema). DBSYNC-006 checks for the container
  and errors out with a pointer if missing.
- `~/.myenvs/ema_nlp.env` loaded for `MONGO_URI`, `POSTGRES_USER`,
  `POSTGRES_DB`, `PG_PORT`, `NEXTCLOUD_DATASETS`. No new env vars introduced
  beyond `STORAGE_BACKEND` (default `nextcloud`) and the optional
  `PG_SYNC_HOST` / `PG_SYNC_USER` / `PG_SYNC_SSH_PORT` for the pull subcommand.
- `jq`, `sha256sum`, `mongodump`/`mongorestore` (host) and the
  `ema_nlp_pg` Docker container (for PG dump). DBSYNC-001/002 add explicit
  `require_cmd` checks so missing dependencies fail loudly with a fix hint.

## What this plan deliberately does NOT do

- No managed-cloud-DB migration. Considered and rejected (see
  `exploration.md` §"What I'd genuinely choose with a free hand"); the
  storage abstraction layer (DBSYNC-001) is the future-swap insurance.
- No automated scheduling / cron-style sync. Manual `export` + manual
  `import` is the model.
- No two-way merge / conflict resolution. The stale-overwrite guard
  (DBSYNC-008) surfaces conflicts but doesn't resolve them — the user picks
  which side wins.
- No changes to the FAISS query cache or other Nextcloud-resident artefacts;
  they continue to sync the same way they do today.
- No new database engines or extensions; logical dumps work against the
  current `pgvector/pgvector:pg16` + `mongo:7.0.22 native` / `8.0.4 Docker`
  combinations unchanged.

## After this work unit

Two follow-ups worth noting (not in this plan):

1. If the gzipped PG dump after the full embedding sweep crosses ~4 GB, the
   storage abstraction layer (DBSYNC-001) makes a swap to MinIO/B2 a
   30-minute job (add a `_put_artifact_minio` function, set
   `STORAGE_BACKEND=minio`).
2. The stale-overwrite guard (DBSYNC-008) is the seed of a richer conflict
   model. If multi-machine data loss ever happens despite the guard, the next
   move is per-row change tracking (CDC) — but only if/when needed.

## Ready for `/next`

`next_available: ["DBSYNC-001", "DBSYNC-002"]`. Either or both first.
