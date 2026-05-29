# MongoDB source DB (ema_nlp)

MongoDB `ema_scraper` is the **source** side of the pipeline: the parsers write
to `parsed_documents` / `link_graph`, and `python -m harness.embed_pg` reads
those collections to populate Postgres. Postgres (`deploy/postgres/`) is the
retrieval target; this is where the data comes from.

## Why this runs in Docker (kernel ≥ 6.19 workaround)

marvin-gpu is on Ubuntu 26.04 / Linux **kernel 7.0**, which MongoDB declares
incompatible — [SERVER-121912](https://jira.mongodb.org/browse/SERVER-121912).
Observed behaviour:

| How MongoDB 8.x is run | Result on kernel 7.0 |
|------------------------|----------------------|
| Native package, **8.0.4** | starts, then **SIGSEGV** ~1 min in |
| Native/Docker, **≥ 8.0.23** (`mongo:8.0`) | **hard-refuses to start** ("known incompatibility") |
| **Docker `mongo:8.0.4`** | **works** ✅ |

A container shares the host **kernel** but bundles its **own userspace**. The
8.0.4 image's older glibc dodges the SIGSEGV that the host's Ubuntu-26.04 glibc
triggers, and 8.0.4 predates the hard kernel gate added in later 8.0.x. Hence
the pinned `mongo:8.0.4` tag in `docker-compose.yml` — **do not bump it** without
re-testing against the live kernel.

The alternative is to reboot into kernel `6.17.0-29-generic` (< 6.19, and the
only older kernel here with the NVIDIA driver built — `6.8.0-45` has none, so no
CUDA). The Docker route avoids the reboot entirely.

## Bring up

Use the unified launcher (starts Postgres + Mongo together):

```bash
scripts/start_services.sh
```

Or directly:

```bash
cd deploy/mongo
docker compose up -d
docker compose ps
docker exec ema_mongo mongosh --quiet --eval "db.adminCommand('ping').ok"   # -> 1
```

Verify it is serving the real data, not an empty DB:

```bash
docker exec ema_mongo mongosh ema_scraper --quiet --eval \
  'printjson(db.getCollectionNames().reduce((a,c)=>(a[c]=db[c].estimatedDocumentCount(),a),{}))'
# expect roughly: parsed_documents ~80k, link_graph ~22.7k, parsed_pdfs ~65k, web_items ~115k
```

## Environment

The compose file reads (defaults in parentheses):

| Var           | Default            | Notes |
|---------------|--------------------|-------|
| `MONGO_UID`   | `109`              | host `mongodb` uid — `id -u mongodb` |
| `MONGO_GID`   | `118`              | host `mongodb` group — `getent group mongodb` |
| `MONGO_PORT`  | `27017`            | published on `127.0.0.1` only |
| `MONGO_DBPATH`| `/var/lib/mongodb` | the native data directory (source of truth) |

Application side, `~/.myenvs/ema_nlp.env` already has:

```
MONGO_URI=mongodb://localhost:27017/
```

## ⚠️ Never run native + container together

Both point at `/var/lib/mongodb`. Two `mongod` processes opening the same
WiredTiger directory will corrupt it. The native `mongod.service` is `enabled`
but cannot run on kernel 7.0 (it dies), so in practice only the container runs
here. If you ever reboot into a < 6.19 kernel and want the native service back,
**stop the container first**:

```bash
cd deploy/mongo && docker compose down
sudo systemctl start mongod
```

`scripts/start_services.sh` guards against this by aborting if the native
`mongod` is active before it starts the container.

## Tear down

```bash
cd deploy/mongo
docker compose down       # stop + remove the container; data on the bind mount is untouched
```

There is no named volume to wipe — the data lives in the host `/var/lib/mongodb`
bind mount and is never destroyed by `docker compose down`.
