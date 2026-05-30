# Postgres + pgvector (ema_nlp)

> ⚠️ **OBSOLETE — being removed.** The retrieval refactor replaced Postgres+pgvector with
> **Neo4j** (see [`docs/RETRIEVAL.md`](../../docs/RETRIEVAL.md) and `deploy/neo4j/`). This
> `deploy/postgres/` stack plus `harness/pg/`, `retrieve_pg.py`, and `embed_pg.py` are
> slated for deletion (LIR-012); `scripts/start_services.sh` no longer starts Postgres.
> Kept only until that cleanup lands.

Local Postgres 16 with pgvector for the EMA narrative corpus. Single supported
install path; the apt route is intentionally not documented to avoid drift
between contributors.

## Image

`pgvector/pgvector:pg16` — official pgvector build on Postgres 16; ships
pgvector >= 0.7 (HNSW support, exceeds the >= 0.5.0 requirement).

## Bring up

```bash
cd deploy/postgres
docker compose up -d
docker compose ps
docker exec -i ema_nlp_pg pg_isready -U ema_nlp -d ema_nlp
docker exec -i ema_nlp_pg psql -U ema_nlp -d ema_nlp \
  -c "CREATE EXTENSION IF NOT EXISTS vector;" \
  -c "SELECT extversion FROM pg_extension WHERE extname='vector';"
```

Expected `pg_isready` exit code 0; expected pgvector version >= 0.5.0.

## Environment

The compose file reads the following env vars (defaults in parentheses):

| Var               | Default     |
|-------------------|-------------|
| `POSTGRES_USER`   | `ema_nlp`   |
| `POSTGRES_PASSWORD` | `ema_nlp` |
| `POSTGRES_DB`     | `ema_nlp`   |
| `PG_PORT`         | `5432`      |

Override by exporting in the shell or via a `.env` file in this directory
(gitignored). Real credentials live in `~/.myenvs/ema_nlp.env` (see
`config.py`).

## Application-side DSN

Add to `~/.myenvs/ema_nlp.env`:

```
PG_DSN=postgresql://ema_nlp:<password>@localhost:5432/ema_nlp
EMA_RETRIEVER=faiss   # flipped to "pgvector" by NARR-028
```

## Schema

DDL lives in `corpus/pg_schema.sql`. Apply (or re-apply) idempotently with
`python scripts/init_db.py`. Use `--reset` to drop and re-create the three
tables (`documents`, `chunks`, `links`).

## Tear down

```bash
cd deploy/postgres
docker compose down            # stop + remove container, keep volume
docker compose down -v         # also wipe the data volume (destructive)
```

## Disk + memory

The named volume `ema_nlp_pgdata` is created on first start. Embeddings at
1024 dims for ~38k PDFs + ~115k HTML pages with average chunking of ~5 chunks
per doc and the HNSW index will land in the low single-digit GB range.
Adjust `shm_size` if `parallel hash join` or maintenance commands report
shared-memory pressure.
