# Setup guide

How to get `ema_nlp` running on a new machine (Linux/macOS).

> **Retrieval stack (Neo4j PropertyGraphIndex):** see [`docs/RETRIEVAL.md`](RETRIEVAL.md)
> for provisioning, env vars, the node/graph model, build + retrieve, and
> troubleshooting. Data services (MongoDB + Neo4j) start via `scripts/start_services.sh`.
> *(The former Postgres+pgvector / FAISS-over-corpus retrieval was deleted in the
> LlamaIndex/Neo4j refactor — LIR-012.)*

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Git | any | `apt install git` / `brew install git` |
| Node.js | 18+ | https://nodejs.org |
| Python | 3.11+ | `apt install python3.11` / `brew install python@3.11` |
| uv *(preferred)* | any | `curl -Lsf https://astral.sh/uv/install.sh \| sh` |
| mongodump / mongorestore | any | `apt install mongodb-database-tools` |
| MongoDB | 6+ | only needed if this machine will hold the live database |

---

## 1. Clone and run the setup script

```bash
git clone https://github.com/MoritzImendoerffer/ema_nlp.git
cd ema_nlp
bash scripts/setup.sh
```

The script does the following (with interactive prompts at each step):

1. Checks Node.js, Python, and uv/pip versions
2. Installs **Claude Code** (`npm install -g @anthropic-ai/claude-code`) if not present
3. Installs Python project dependencies (`pip install -e ".[dev]"`)
4. Clones the `claude-code-toolkit` plugin repo to `~/github_repos/claude-code-toolkit`
   (required for custom Claude Code skills; Claude Code still works without it)
5. Creates `~/.myenvs/ema_nlp.env` interactively (see section 2)

---

## 2. Environment file — `~/.myenvs/ema_nlp.env`

**Credentials are never stored in this repository.** All secrets live in
`~/.myenvs/ema_nlp.env` on each machine. The file is created by `setup.sh`
or you can create it manually:

```bash
mkdir -p ~/.myenvs
touch ~/.myenvs/ema_nlp.env
chmod 600 ~/.myenvs/ema_nlp.env
```

### Required variables

```bash
# Anthropic API key — https://console.anthropic.com/settings/keys
ANTHROPIC_API_KEY=sk-ant-...
```

### Chat UI variables

```bash
# JWT secret for Chainlit session signing — REQUIRED to run app.py.
# Generate once per machine with: python3 -c "import secrets; print(secrets.token_hex(32))"
# Without this, Chainlit raises: ValueError: You must provide a JWT secret...
CHAINLIT_AUTH_SECRET=<64-char hex string>

# Login password for the chat UI (default: "dev").
# Override to set a stronger password for shared/exposed instances.
# UI_PASSWORD=dev
```

### Optional variables

```bash
# MongoDB URI for this machine (default: mongodb://localhost:27017/)
# Change only if MongoDB runs on a non-standard port or requires auth.
# MONGO_URI=mongodb://localhost:27017/

# Neo4j (retrieval store). Password must be >= 8 chars (Neo4j 5.x). If a native
# Neo4j already holds 7474/7687, run the project container on alt ports
# (NEO4J_BOLT_PORT=7688 docker compose -f deploy/neo4j/docker-compose.yml up -d)
# and set NEO4J_URI to match.
# NEO4J_URI=bolt://localhost:7687
# NEO4J_USER=neo4j
# NEO4J_PASSWORD=ema_nlp_dev_pw

# Active index profile (default: neo4j_hier -> harness/configs/index/neo4j_hier.yaml)
# Selects the retrieval store/strategy. neo4j_hier is the only built profile;
# others in docs/RETRIEVAL_TRACKS.md are spec-only.
# EMA_INDEX_PROFILE=neo4j_hier

# Phoenix tracing endpoint for the chat UI (default: http://localhost:6006)
# app.py reads PHOENIX_URL and registers tracing via phoenix.otel at startup.
# PHOENIX_URL=http://localhost:6006

# ── Corpus and index paths (LEGACY — not used by retrieval) ─────────────────────
# config.py still defines CORPUS_PATH (EMA_CORPUS_PATH) and INDEX_DIR
# (EMA_INDEX_PATH), but the FAISS-over-corpus.jsonl chat-UI path they belonged to
# was deleted in the LlamaIndex/Neo4j refactor (LIR-012). Retrieval now runs over
# the Neo4j PropertyGraphIndex, selected by EMA_INDEX_PROFILE (above). corpus.jsonl
# is benchmark-only. You do not need to set these. See docs/RETRIEVAL.md.
```

### LLM and embedding model settings

These variables let you swap models and providers without touching any code.
All are optional — the defaults match the project's current configuration.

```bash
# ── Anthropic API endpoint ────────────────────────────────────────────────────
# Default endpoint is https://api.anthropic.com.
# Override when using a third-party gateway (e.g. https://gw.claudeapi.com).
# ANTHROPIC_BASE_URL=https://api.anthropic.com

# ── LLM model (used by judge, rerankers, and chat UI) ─────────────────────────
# Any model name accepted by the Anthropic API (or your gateway).
# The chat UI also accepts EMA_CLAUDE_MODEL as a more specific override.
#
# Fast / cheap (default):
# EMA_LLM_MODEL=claude-haiku-4-5-20251001
#
# Better quality — useful for the judge and synthesis:
# EMA_LLM_MODEL=claude-sonnet-4-6
#
# Highest quality (slower, more expensive):
# EMA_LLM_MODEL=claude-opus-4-7

# ── Embedding model ───────────────────────────────────────────────────────────
# Controls what index is built and how queries are embedded at retrieval time.
# Changing this requires rebuilding the Neo4j PropertyGraphIndex (re-run
# harness.indexing.build_index). The default BGE-large is what the live graph
# (5.82M leaf embeddings) was built with — see docs/RETRIEVAL.md.
#
# Provider: "huggingface" (default, runs locally, no API key needed)
#           "openai"      (requires OPENAI_API_KEY; needs: pip install -e ".[ui]")
# EMA_EMBED_PROVIDER=huggingface
#
# HuggingFace model examples:
#   Large (default, best quality, ~1.3 GB):
#   EMA_EMBED_MODEL=BAAI/bge-large-en-v1.5
#
#   Small (faster, lower memory, slightly lower recall):
#   EMA_EMBED_MODEL=BAAI/bge-small-en-v1.5
#
#   Multilingual (if non-English content is added later):
#   EMA_EMBED_MODEL=intfloat/multilingual-e5-large
#
# OpenAI model examples (provider must be set to "openai"):
#   EMA_EMBED_PROVIDER=openai
#   EMA_EMBED_MODEL=text-embedding-3-small    # cheap, 1536-dim
#   EMA_EMBED_MODEL=text-embedding-3-large    # best quality, 3072-dim
```

**Precedence (high → low):**
1. YAML run-config field (`embed_model:`, `model:`) — per-run override
2. `EMA_*` env vars in `~/.myenvs/ema_nlp.env` — machine default
3. Code constant in `harness/providers.py` — fallback (`claude-haiku-4-5-20251001` / `BAAI/bge-large-en-v1.5`)

**Example: lighter setup for a laptop with limited RAM**

```bash
# ~/.myenvs/ema_nlp.env
ANTHROPIC_API_KEY=sk-ant-...
EMA_LLM_MODEL=claude-haiku-4-5-20251001
EMA_EMBED_MODEL=BAAI/bge-small-en-v1.5   # ~130 MB instead of ~1.3 GB
```

**Example: third-party API gateway**

```bash
# ~/.myenvs/ema_nlp.env
ANTHROPIC_API_KEY=sk-Z7VX3f...            # key issued by the gateway
ANTHROPIC_BASE_URL=https://gw.claudeapi.com
EMA_LLM_MODEL=claude-sonnet-4-6
```

`config.py` loads this file via `python-dotenv` at import time
(`override=False`, so a variable already set in the shell always wins).

---

## 3. Authenticate Claude Code

On first run Claude Code opens a browser for OAuth login:

```bash
claude
```

To verify everything is wired up correctly:

```bash
/doctor    # inside a Claude Code session
```

---

## 4. Verify the Python install

```bash
pytest          # all tests should pass
ruff check .    # no lint errors
```

---

## 5. MongoDB sync

The scraped EMA data lives in a MongoDB database (`ema_scraper`) with three
collections: `web_items` (raw HTML), `parsed_pdfs` (PDF markdown), and
`parsed_documents` (~80k canonical parser output — the indexing source). On this
host MongoDB runs as the pinned `mongo:8.0.4` Docker container via
`scripts/start_services.sh` (the native package crashes on kernel ≥ 7.0 —
SERVER-121912; see `deploy/mongo/README.md`).

> The earlier `scripts/sync_mongo.sh` helper (Nextcloud-archive / SSH-pull modes)
> has been removed. Move the database between machines with raw `mongodump` /
> `mongorestore` when needed.

**On the source machine (export):**

```bash
mongodump --uri "mongodb://localhost:27017" --db ema_scraper \
  --archive=ema_scraper.archive --gzip
```

**On the destination machine (import):**

```bash
# --drop replaces the existing local ema_scraper database
mongorestore --uri "mongodb://localhost:27017" --gzip --drop \
  --archive=ema_scraper.archive
```

Transfer the `ema_scraper.archive` file between machines however is convenient
(`scp`, a shared Nextcloud folder, etc.).

### Sync safety rules

- `mongorestore --drop` **replaces the local database** — make sure you are
  restoring the dump you expect (check the archive timestamp first).
- Corpus JSONL files (`corpus/corpus.jsonl`) and benchmark files are
  versioned in Git and do not need MongoDB sync.

---

## 6. Arize Phoenix — tracing and HITL annotation

Phoenix is the trace store and HITL labelling UI. Every LLM call and
retrieval step is captured as a span tree in Phoenix, which the SME
uses to label answer quality and individual tool-call quality.

### Phoenix hosting

Phoenix runs locally on the same host as the chat UI (marvin-gpu is the single
project host). Start it once at boot:

```bash
python -c "import phoenix as px; px.launch_app()"
# or as a background service — see phoenix docs
```

If you run Phoenix on a different host (or a non-default port), point the chat UI
at it via `~/.myenvs/ema_nlp.env`:

```bash
PHOENIX_URL=http://localhost:6006
```

`app.py` reads `PHOENIX_URL` and registers tracing via `phoenix.otel` at startup
(`auto_instrument=True`, posting spans to `<PHOENIX_URL>/v1/traces`). If unset, it
defaults to `http://localhost:6006`. Set `PHOENIX_DISABLED=1` to turn tracing off.

### Phoenix annotation schemas

Create these two annotation configs once in the Phoenix UI
(*Settings → Annotations → New annotation*):

**`step_quality`** — labels individual tool-call, thought, and observe spans:
- Type: **Categorical**
- Values: `good`, `suboptimal`, `wrong`
- Use: attach to spans whose `span_kind` is `TOOL` or whose name starts
  with `think` / `act` / `observe`

**`answer_quality`** — labels the root span (final answer):
- Type: **Continuous** (1–5 scale)
- Also add a freeform **`reason`** string annotation on the same span
- Use: attach to the top-level workflow span

### Annotation queues (per strategy)

Create one annotation queue per strategy you are actively labelling.
In the Phoenix UI (*Datasets → Annotation Queues → New queue*):

| Queue name | Filter |
|------------|--------|
| `recent_crag` | `attributes.workflow_name = "crag"` |
| `recent_react` | `attributes.workflow_name = "react"` |

Work through spans in each queue during an SME session; label both
`step_quality` (per tool call) and `answer_quality` (root span).

### Exporting annotations to Nextcloud

After each labelling session, export the Phoenix annotations to the
shared Nextcloud JSONL store so the few-shot injection system can use them:

```bash
python -m harness.hitl.export_annotations --since 2026-05-23
```

Output: `~/Nextcloud/Datasets/ema_nlp/annotations/YYYY-MM-DD.jsonl`

See `harness/hitl/export_annotations.py` for `--strategy` and
`--dry-run` flags.

---

## 7. Eval results directory

> **The eval / LLM-judge / benchmark-runner suite (`run_eval.py`, the lift
> metric, `harness/eval*`, `metrics*`) is not on this branch** — it was archived
> to `archive/pre-llamaindex-refactor` pending a rebuild on the Neo4j retrieval
> API. The results/symlink machinery below applies only to that archived suite;
> nothing on `refactor/llamaindex-retrieval-pipeline` writes eval results yet.

When the eval suite is rebuilt, results are **not stored in the repo** — they live
in Nextcloud and are accessed via a symlink:

```
~/Nextcloud/Datasets/ema_nlp/results/   ← actual data
ema_nlp/results                          ← symlink → above path
```

The symlink is listed in `.gitignore` so it is transparent to git.

### On a new machine

```bash
mkdir -p ~/Nextcloud/Datasets/ema_nlp/results
ln -s ~/Nextcloud/Datasets/ema_nlp/results /path/to/ema_nlp/results
```

### Directory layout on Nextcloud

```
~/Nextcloud/Datasets/ema_nlp/
├── corpus/              ← corpus.jsonl + filter/dedup logs
├── results/             ← one sub-directory per eval run (archived suite)
│   ├── baseline_a0plus/
│   │   ├── config.yaml
│   │   ├── retrieval.json
│   │   ├── results.json
│   │   ├── metrics.png
│   │   └── run_summary.md
│   └── ...
└── annotations/         ← Phoenix HITL export JSONL files
```

> The retrieval store itself is **not** a file on Nextcloud — it is the Neo4j
> PropertyGraphIndex (Docker), built by `harness.indexing.build_index` from Mongo
> `parsed_documents`. There is no longer a FAISS-over-corpus `index/` directory
> (the FAISS query cache lives in the repo at `harness/query_cache.py`).
