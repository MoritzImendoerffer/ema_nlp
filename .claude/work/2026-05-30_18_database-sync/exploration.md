# Database sync — option survey & recommended architecture

## 1. The existing mongo half (baseline to mirror)

`scripts/sync_mongo.sh` already nails the ergonomic pattern we want to
replicate for Postgres:

- Uses `mongodump --archive=<file>` → single-file blob on Nextcloud
  (`~/Nextcloud/Datasets/mongo_sync/ema_scraper.archive`).
- `import` does `mongorestore --drop --archive=...` after a `[y/N]`
  confirm-before-drop prompt.
- Loads env from `~/.myenvs/ema_nlp.env` so credentials never live in the
  repo.
- Has an SSH-live `pull` mode that pipes `mongodump | mongorestore` over
  Tailscale, no Nextcloud round-trip.
- Reports `web_items` document count on both sides as a smoke-check.

What it does NOT have, and is worth fixing while we're here:
- No checksum on the archive — a half-uploaded Nextcloud file would silently
  half-restore.
- No manifest — receiver can't tell what machine the archive came from or
  when it was taken without `stat`-ing the file.
- No `--gzip`: archive is uncompressed (Nextcloud's transport gzips but the
  on-disk file is ~3.4 GB raw vs ~1.3 GB if `--gzip` were on).

## 2. Postgres dump/restore — the option space

We have four real choices. All produce a file we can drop on Nextcloud; the
question is fidelity vs. portability vs. speed.

| Option | Tool | Format | Restore tool | Portable across PG versions? | HNSW index preserved? | Restore speed (rough) | Cross-machine safety |
|--------|------|--------|--------------|------------------------------|------------------------|------------------------|----------------------|
| **A. Logical, custom format** | `pg_dump -Fc -Z 6` | Single compressed binary file | `pg_restore` | Yes (within ±1 major) | DDL only; index **rebuilt** on restore | Medium (HNSW rebuild dominates) | **High** ✅ |
| B. Logical, directory + parallel | `pg_dump -Fd -j N` | Multi-file directory | `pg_restore -j N` | Yes | DDL only; rebuilt | Faster than A on big DBs | Medium (multi-file = atomicity headache on Nextcloud) |
| C. Physical base backup | `pg_basebackup -Ft -z` | tarball(s) of `$PGDATA` | Stop server, untar, start | **No** — must match exact PG major + extension versions | Yes — index files copied as-is | Fastest restore | Low (locks us to identical Docker images on every machine) |
| D. File-level data dir copy | `tar` of the Docker volume | Single tarball | `tar -x` into stopped volume | No | Yes | Fast | Lowest (must stop PG cold; any version drift breaks it) |

**Recommendation: A (logical custom-format dump).**

Why A wins for this workload:
- The user runs `pgvector/pgvector:pg16` everywhere — but pinning the image
  shouldn't be a requirement of the sync mechanism (a future PG17 bump should
  not invalidate yesterday's archive). Logical dumps survive engine upgrades;
  physical dumps don't.
- Custom format is a single file → trivial for atomic Nextcloud sync (`.partial`
  rename pattern + sha256 manifest).
- `pg_restore` knows how to drop+recreate selectively (`--clean --if-exists`),
  giving the same `--drop` semantics as `mongorestore`.
- HNSW rebuild cost is real (see §5 sizing) but acceptable: at today's 42k
  chunks it's a 1–3 minute one-time hit on import; even after the full sweep
  it's ~30 min. The alternative (option C) couples every machine to the
  exact image tag and breaks the moment one of them pulls a patch.
- pgvector's `vector` type round-trips perfectly in custom format —
  serialized as `[0.123, 0.456, …]` text inside the binary dump; restored
  via the `vector` extension which the image preinstalls.

When option B (directory + parallel) would matter: dump and restore are CPU/IO
bound on tables larger than ~10 GB. We're nowhere near that. The atomicity
cost on Nextcloud (multiple files arriving out of order) is not worth the
modest speedup.

When option C (base backup) would matter: ops scenario where the embedding
sweep needs to ship to many identical workers fast. Single-developer cross-
machine sync isn't that.

## 3. Running pg_dump against the Dockerised PG

The cleanest invocation, requiring no host-side PG client:

```bash
docker exec ema_nlp_pg pg_dump \
    --format=custom --compress=6 --no-owner --no-privileges \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  > "$ARCHIVE_FILE"
```

Restore (symmetric):

```bash
docker exec -i ema_nlp_pg pg_restore \
    --clean --if-exists --no-owner --no-privileges \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  < "$ARCHIVE_FILE"
```

Why these flags:
- `--no-owner --no-privileges` — receiving DB might be owned by a different
  role (e.g. POSTGRES_USER differs between machines); strip ownership SQL so
  the restore doesn't trip on "role does not exist" errors.
- `--clean --if-exists` — drop objects before recreating, so re-import over
  a populated DB doesn't fail on UNIQUE/PK conflicts. Matches Mongo `--drop`.
- `--compress=6` — pgvector embeddings are float32, which compress decently
  (`-Z 6` typical ~2× on dense vectors); `-Z 9` doubles dump time for ~5%
  more compression. Not worth it.
- `--format=custom` — selective restore is possible later if we ever need
  to skip a table (e.g. `--exclude-table=chunks` for a no-embeddings dump).

Limitation: `--clean` requires the target DB and schema to exist; the script
must create them first if missing. `start_services.sh` already handles this
via `scripts/init_db.py` which applies `corpus/pg_schema.sql`. Restore step
order:

1. `start_services.sh` (creates DB + applies schema, idempotent).
2. `pg_restore --clean --if-exists` (drops + reinserts; pgvector extension
   already present via schema bootstrap).

## 4. The mongo half — small upgrades worth folding in

While we're touching this code, three cheap wins:

- Add `--gzip` to `mongodump` / `mongorestore` invocations. Cuts archive size
  ~60% with negligible CPU.
- Compute sha256 on export, store in `manifest.json`, verify on import. Catches
  Nextcloud partial uploads.
- Write the manifest *last* so the receiver can use its presence as a signal
  the archive is complete.

These are additive; the existing archive format stays readable by older
`sync_mongo.sh` versions during the transition.

## 5. Size estimates (where the wall-clock and bytes go)

Current marvin-gpu state (per HISTORY 2026-05-29 and live `db.stats()` from
this laptop):

**Mongo `ema_scraper`:**
- `web_items`: 115k docs, ~1.6 GB raw / ~478 MB storage (laptop)
- `parsed_pdfs`: 65k docs, ~1.8 GB raw / ~798 MB storage (laptop)
- `parsed_documents`: 80k docs, est. ~1.5 GB raw (marvin-gpu only)
- `link_graph`: 22k rows holding 2.28M anchors, est. ~400 MB (marvin-gpu only)
- **Total raw**: ~5.3 GB. **Compressed archive estimate**: ~1.8 GB gzipped.

**Postgres `ema_nlp` (marvin-gpu state, pre-sweep):**
- 8,852 documents (parsed_text is the heaviest column)
- 42,913 chunks × 1024-dim float32 vectors ≈ 176 MB just for vectors
- HNSW index on `embedding` ≈ 1.5–2× vector size ≈ 300 MB
- tsvector GIN + trgm indexes + links table ≈ 100 MB
- **Total on-disk**: ~700 MB. **Compressed custom dump**: ~300 MB.

**After the pending embedding sweep (71k pending → ~350–700k chunks):**
- Vectors: ~3 GB
- HNSW: ~5 GB
- **Total on-disk**: ~10 GB. **Compressed custom dump**: ~3–5 GB.

Combined Nextcloud footprint after the sweep: **~5–7 GB**. Sync time over a
50 Mbit upstream: ~15–25 min. One-time hit, then daily diffs are zero
(Nextcloud only re-uploads on overwrite).

Restore-side wall clock:
- Mongo: ~2–4 min per GB of archive → ~5–10 min total.
- PG without HNSW: ~3–5 min.
- HNSW rebuild on 700k chunks: ~30 min (pgvector single-threaded build).
- **End-to-end fresh-machine bootstrap**: ~45–60 min once Nextcloud has
  downloaded the archives. Most of that is the index rebuild, which is
  unavoidable for any logical-dump approach.

## 6. Manifest schema (proposed)

A single `manifest.json` alongside the archives, written last by the
exporter, validated first by the importer:

```json
{
  "schema_version": 1,
  "exported_at": "2026-05-30T14:32:18+00:00",
  "source_host": "marvin-gpu",
  "git_commit": "d5263a9",
  "mongo": {
    "archive": "mongo.archive.gz",
    "bytes": 1932847614,
    "sha256": "8a3f…",
    "db_name": "ema_scraper",
    "key_counts": {
      "web_items": 115101,
      "parsed_documents": 80083,
      "link_graph": 22743
    }
  },
  "postgres": {
    "archive": "pg.dump",
    "bytes": 312456789,
    "sha256": "44b1…",
    "db_name": "ema_nlp",
    "key_counts": {
      "documents": 8852,
      "chunks": 42913,
      "links": 36741
    }
  }
}
```

Importer responsibilities, in order:
1. Read manifest, refuse if missing.
2. Verify sha256 of each archive; refuse on mismatch (likely a half-synced
   Nextcloud file).
3. Print source hostname, age, sizes, and key counts.
4. Compare against local counts; warn loudly if the local DB has rows newer
   than the archive (probable data-loss scenario).
5. Single `[y/N]` confirmation covering both DROPs.
6. Restore each DB sequentially; print final counts; exit non-zero if they
   don't match the manifest.

## 7. Recommended script layout

Three files. The first is the entry point the user will type 99% of the
time; the others are reusable building blocks.

```
scripts/
├── sync_databases.sh   # NEW: unified wrapper. The "single script".
├── sync_mongo.sh       # EXISTING: kept + extended (gzip + sha256).
└── sync_pg.sh          # NEW: symmetric to sync_mongo.sh.
```

`scripts/sync_databases.sh`:
- `export` → calls `sync_mongo.sh export --yes` + `sync_pg.sh export --yes`,
  then writes the combined `manifest.json`.
- `import` → reads `manifest.json`, single confirmation, then
  `sync_mongo.sh import --yes --skip-checksum` + `sync_pg.sh import --yes
  --skip-checksum` (checksums already verified by the wrapper).
- `status` → shows: Nextcloud archive age + size + source host + key counts
  vs. local DB counts. No DB modifications.
- `--only mongo|pg` for partial operation.
- `--no-embeddings` (pass-through to `sync_pg.sh`) excludes the `chunks`
  table for pre-sweep development sync.

`scripts/sync_pg.sh` — same shape as `sync_mongo.sh`:
- `export` writes `~/Nextcloud/Datasets/db_sync/pg.dump` via
  `docker exec ema_nlp_pg pg_dump …`.
- `import` runs `pg_restore` inside the container.
- `pull --host X` does SSH-live: `ssh X 'docker exec ema_nlp_pg pg_dump …' |
  docker exec -i ema_nlp_pg pg_restore …`.
- `--no-embeddings` flag → adds `--exclude-table=chunks --exclude-table-data=chunks`
  to `pg_dump` and skips HNSW rebuild on restore (chunks rebuilt via
  `harness.embed_pg` on the destination).

## 8. The "single script" experience the user asked for

The intended round-trip from the user's keyboard:

```bash
# On marvin-gpu, after a productive session:
bash scripts/sync_databases.sh export
# → Dumps both DBs, writes manifest, prints sync ETA.
# → Wait for Nextcloud client to upload (it'll go on its own).

# On the laptop, the next morning:
bash scripts/sync_databases.sh status
# → "Archive from marvin-gpu, 14 hours old, 4.3 GB; local DBs are empty.
#    Ready to import."

bash scripts/sync_databases.sh import
# → Reads manifest, verifies checksums, asks once for confirmation,
#    restores both DBs, prints count diff, done.
```

If the user only wants one DB synced (e.g. quick mongo refresh):

```bash
bash scripts/sync_databases.sh export --only mongo
bash scripts/sync_databases.sh import --only mongo
```

For development iteration without the embedding payload:

```bash
bash scripts/sync_databases.sh export --no-embeddings
# → Mongo full, Postgres without chunks table. Archive shrinks 10×.
```

## 9. What this work unit does NOT change

- The existing `sync_mongo.sh` keeps working unchanged for users who have it
  in muscle memory.
- No changes to the data model or any data layer code.
- No changes to `start_services.sh` (the new scripts assume PG is already up).
- No changes to `~/Nextcloud/Datasets/ema_nlp/` (corpus/index/results stay
  where they are; the new `db_sync/` is a sibling, not a child).

## 10. Implementation order (high-level — full breakdown in /plan)

1. `sync_pg.sh` with `export`/`import` only.
2. Migrate `sync_mongo.sh` archive path to the consolidated `db_sync/` dir
   (with a one-time symlink for back-compat). Add gzip + sha256.
3. `manifest.json` writer + verifier as a small shared bash helper sourced
   by both per-DB scripts.
4. `sync_databases.sh` wrapper with `export`/`import`/`status`.
5. `sync_pg.sh pull` (SSH live mode).
6. `--no-embeddings` flag end-to-end.
7. `docs/SYNC.md` with the round-trip recipe and a troubleshooting section
   (sha256 mismatch, partial Nextcloud upload, HNSW rebuild time).
8. Smoke test on this laptop: export an empty PG → import → confirm
   round-trip succeeds. Then a "real" test once you're back on marvin-gpu.
