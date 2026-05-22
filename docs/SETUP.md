# Setup guide

How to get `ema_nlp` running on a new machine (Linux/macOS).

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

### Optional variables

```bash
# MongoDB URI for this machine (default: mongodb://localhost:27017/)
# Change only if MongoDB runs on a non-standard port or requires auth.
# MONGO_URI=mongodb://localhost:27017/

# Path to Nextcloud datasets folder (default: ~/Nextcloud/Datasets)
# Used by the MongoDB sync scripts to find/write the archive file.
# NEXTCLOUD_DATASETS=~/Nextcloud/Datasets

# --- Only needed for the SSH live-pull sync (scripts/sync_mongo.sh pull) ---
# Tailscale hostname or IP of the machine with the up-to-date MongoDB.
# MONGO_SYNC_HOST=your-pc-tailscale-hostname-or-ip
# MONGO_SYNC_USER=moritz
# MONGO_SYNC_SSH_PORT=22

# ── Corpus and index paths ─────────────────────────────────────────────────────
# Path to the Q&A corpus JSONL used to build the FAISS index.
# Default: corpus/corpus.jsonl (26 k records).
# Override when experimenting with a smaller or custom corpus.
# After changing this, delete harness/index/ to force a rebuild.
# EMA_CORPUS_PATH=/path/to/corpus.jsonl

# Path to the FAISS index directory (default: harness/index/).
# EMA_INDEX_PATH=/path/to/index/
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
# Changing this requires rebuilding the index (set force_rebuild: true in the
# run config, or delete harness/index/).
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

### LangSmith experiment tracking

The `harness/chains/` module uses LangSmith for batch experiment tracking and
dataset-based evaluation (separate from Arize Phoenix, which handles the
interactive chat UI).

```bash
# ── LangSmith (https://smith.langchain.com) ───────────────────────────────────
# Get your key at https://smith.langchain.com → Settings → API Keys
LANGSMITH_API_KEY=lsv2_...

# Enable automatic tracing for all LangChain/LangGraph calls
LANGCHAIN_TRACING_V2=true

# Project name in LangSmith dashboard (creates the project if it doesn't exist)
LANGCHAIN_PROJECT=ema-nlp
```

Without these variables set, `harness/chains/` still works — chains run
normally but traces are not sent to LangSmith. The `run_langsmith_eval.py`
CLI requires `LANGSMITH_API_KEY` to upload datasets and experiments.

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

The scraped EMA data lives in a MongoDB database (`ema_scraper` /
`web_items`). Two sync methods are available depending on whether both
machines are online at the same time.

### Method A — Nextcloud file sync (recommended, async)

Works even when only one machine is on. Uses a dump file in your
Nextcloud folder as the transfer medium; Nextcloud syncs it automatically.

**On the source machine (export):**

```bash
bash scripts/sync_mongo.sh export
```

This writes `~/Nextcloud/Datasets/mongo_sync/ema_scraper.archive`.
Wait until Nextcloud has fully synced the file before restoring
(check the Nextcloud tray icon or `nextcloud-desktop` status).

**On the destination machine (import):**

```bash
bash scripts/sync_mongo.sh import
```

This reads the archive from the same Nextcloud path and restores it
locally, dropping the existing local database first after confirmation.

> **Direction is symmetric** — export on PC, import on laptop; or export
> on laptop, import on PC. Whoever exported last wins.

### Method B — SSH live-pull (both machines online, Tailscale)

Streams `mongodump` output directly from the remote machine over SSH.
No MongoDB port needs to be exposed — only SSH/22 is required.

```bash
bash scripts/sync_mongo.sh pull --host <tailscale-ip-or-hostname>
```

The `--host` flag (and `--user`, `--port`) can be set in
`~/.myenvs/ema_nlp.env` as `MONGO_SYNC_HOST` / `MONGO_SYNC_USER` /
`MONGO_SYNC_SSH_PORT` so you don't have to type them each time.

### Sync safety rules

- Both methods **drop the local database** before restoring — always
  confirm the prompt before proceeding.
- For Method A, check the archive timestamp before importing
  (`ls -lh ~/Nextcloud/Datasets/mongo_sync/`) to make sure you are
  restoring the version you expect.
- Corpus JSONL files (`corpus/corpus.jsonl`) and benchmark files are
  versioned in Git and do not need MongoDB sync.
