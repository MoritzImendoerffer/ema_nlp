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
