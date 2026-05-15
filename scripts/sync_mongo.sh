#!/usr/bin/env bash
# sync_mongo.sh — synchronise the ema_scraper MongoDB database between machines.
#
# SUBCOMMANDS
#   export   Dump the local database to ~/Nextcloud/Datasets/mongo_sync/
#            (Nextcloud then syncs the file to other machines automatically)
#
#   import   Restore the local database from the Nextcloud archive
#            (run after Nextcloud has finished syncing on this machine)
#
#   pull     Live one-way pull via SSH + Tailscale (both machines must be on)
#            scripts/sync_mongo.sh pull --host <tailscale-ip> [--user <user>]
#
# CREDENTIALS
#   No credentials are stored in this script or the repository.
#   Optional env vars (loaded from ~/.myenvs/ema_nlp.env if present):
#     NEXTCLOUD_DATASETS   path to Nextcloud datasets folder (default: ~/Nextcloud/Datasets)
#     MONGO_URI            local MongoDB URI (default: mongodb://localhost:27017/)
#     MONGO_SYNC_HOST      remote host for 'pull' subcommand
#     MONGO_SYNC_USER      SSH user for 'pull' subcommand (default: $USER)
#     MONGO_SYNC_SSH_PORT  SSH port for 'pull' subcommand (default: 22)

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[ok]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
err()  { echo -e "${RED}[error]${NC} $*"; exit 1; }

# ── Load env file ─────────────────────────────────────────────────────────────
ENV_FILE="$HOME/.myenvs/ema_nlp.env"
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    set -o allexport; source "$ENV_FILE"; set +o allexport
fi

# ── Defaults ──────────────────────────────────────────────────────────────────
DB_NAME="ema_scraper"
LOCAL_MONGO_URI="${MONGO_URI:-mongodb://localhost:27017/}"
NX_DATASETS="${NEXTCLOUD_DATASETS:-$HOME/Nextcloud/Datasets}"
ARCHIVE_DIR="${NX_DATASETS}/mongo_sync"
ARCHIVE_FILE="${ARCHIVE_DIR}/ema_scraper.archive"

# SSH pull defaults (only used by 'pull' subcommand)
REMOTE_HOST="${MONGO_SYNC_HOST:-}"
REMOTE_USER="${MONGO_SYNC_USER:-$USER}"
REMOTE_PORT="${MONGO_SYNC_SSH_PORT:-22}"

# ── Helpers ───────────────────────────────────────────────────────────────────
require_cmd() { command -v "$1" &>/dev/null || err "$1 not found. Install mongodb-database-tools."; }

confirm_drop() {
    echo ""
    echo -e "${YELLOW}[!]${NC} This will DROP the local '${DB_NAME}' database and replace it."
    read -r -p "    Continue? [y/N] " CONFIRM
    [[ "${CONFIRM:-N}" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
}

local_count() {
    mongosh --quiet --uri "${LOCAL_MONGO_URI}" \
        --eval "db.getSiblingDB('${DB_NAME}').web_items.countDocuments()" 2>/dev/null \
        || echo "unknown"
}

# ── Subcommand: export ────────────────────────────────────────────────────────
cmd_export() {
    require_cmd mongodump

    echo ""
    echo "=== MongoDB export → Nextcloud ==="
    echo "  Source : ${LOCAL_MONGO_URI} / ${DB_NAME}"
    echo "  Archive: ${ARCHIVE_FILE}"
    echo ""

    COUNT=$(local_count)
    echo "  Local document count (web_items): ${COUNT}"

    if [ -f "$ARCHIVE_FILE" ]; then
        MTIME=$(date -r "$ARCHIVE_FILE" "+%Y-%m-%d %H:%M" 2>/dev/null || stat -c "%y" "$ARCHIVE_FILE" | cut -d. -f1)
        warn "Existing archive from ${MTIME} will be overwritten."
    fi

    echo ""
    read -r -p "Export now? [Y/n] " CONFIRM
    [[ "${CONFIRM:-Y}" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

    mkdir -p "$ARCHIVE_DIR"
    START=$(date +%s)
    mongodump --uri "${LOCAL_MONGO_URI}" --db "${DB_NAME}" --archive="${ARCHIVE_FILE}"
    END=$(date +%s)

    SIZE=$(du -sh "$ARCHIVE_FILE" | cut -f1)
    ok "Export complete in $(( END - START ))s — archive: ${SIZE} at ${ARCHIVE_FILE}"
    echo ""
    echo "Next: wait for Nextcloud to sync, then run on the other machine:"
    echo "  bash scripts/sync_mongo.sh import"
    echo ""
}

# ── Subcommand: import ────────────────────────────────────────────────────────
cmd_import() {
    require_cmd mongorestore

    echo ""
    echo "=== MongoDB import ← Nextcloud ==="
    echo "  Archive: ${ARCHIVE_FILE}"
    echo "  Target : ${LOCAL_MONGO_URI} / ${DB_NAME}"
    echo ""

    [ -f "$ARCHIVE_FILE" ] || err "Archive not found: ${ARCHIVE_FILE}\nRun 'sync_mongo.sh export' on the source machine first and wait for Nextcloud to sync."

    MTIME=$(date -r "$ARCHIVE_FILE" "+%Y-%m-%d %H:%M" 2>/dev/null || stat -c "%y" "$ARCHIVE_FILE" | cut -d. -f1)
    SIZE=$(du -sh "$ARCHIVE_FILE" | cut -f1)
    echo "  Archive date : ${MTIME}"
    echo "  Archive size : ${SIZE}"

    confirm_drop

    START=$(date +%s)
    mongorestore --drop --archive="${ARCHIVE_FILE}" --db "${DB_NAME}" --uri "${LOCAL_MONGO_URI}"
    END=$(date +%s)

    COUNT=$(local_count)
    ok "Import complete in $(( END - START ))s — local web_items count: ${COUNT}"
    echo ""
}

# ── Subcommand: pull (SSH live) ───────────────────────────────────────────────
cmd_pull() {
    # Parse pull-specific flags
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --host) REMOTE_HOST="$2"; shift 2 ;;
            --user) REMOTE_USER="$2"; shift 2 ;;
            --port) REMOTE_PORT="$2"; shift 2 ;;
            *) err "Unknown pull flag: $1" ;;
        esac
    done

    require_cmd mongorestore
    command -v ssh &>/dev/null || err "ssh not found."
    [ -n "$REMOTE_HOST" ] || err "Remote host required. Use --host <host> or set MONGO_SYNC_HOST in ~/.myenvs/ema_nlp.env"

    echo ""
    echo "=== MongoDB live pull (SSH) ==="
    echo "  Remote : ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PORT}"
    echo "  DB     : ${DB_NAME}"
    echo "  Local  : ${LOCAL_MONGO_URI}"
    echo ""

    ssh -p "$REMOTE_PORT" -o ConnectTimeout=10 "${REMOTE_USER}@${REMOTE_HOST}" \
        "command -v mongodump" &>/dev/null \
        || err "mongodump not found on remote ${REMOTE_HOST}. Install mongodb-database-tools there."

    REMOTE_COUNT=$(ssh -p "$REMOTE_PORT" "${REMOTE_USER}@${REMOTE_HOST}" \
        "mongosh --quiet --eval 'db.getSiblingDB(\"${DB_NAME}\").web_items.countDocuments()'" \
        2>/dev/null || echo "unknown")
    echo "  Remote web_items count: ${REMOTE_COUNT}"

    confirm_drop

    START=$(date +%s)
    ssh -p "$REMOTE_PORT" "${REMOTE_USER}@${REMOTE_HOST}" \
        "mongodump --db ${DB_NAME} --archive" \
      | mongorestore --drop --archive --db "${DB_NAME}" --uri "${LOCAL_MONGO_URI}"
    END=$(date +%s)

    LOCAL_COUNT=$(local_count)
    ok "Pull complete in $(( END - START ))s."
    echo "  Remote count : ${REMOTE_COUNT}"
    echo "  Local count  : ${LOCAL_COUNT}"
    echo ""
}

# ── Dispatch ──────────────────────────────────────────────────────────────────
SUBCOMMAND="${1:-}"
shift || true

case "$SUBCOMMAND" in
    export) cmd_export "$@" ;;
    import) cmd_import "$@" ;;
    pull)   cmd_pull   "$@" ;;
    ""|--help|-h)
        echo "Usage: sync_mongo.sh <subcommand> [flags]"
        echo ""
        echo "Subcommands:"
        echo "  export          Dump local DB to Nextcloud archive"
        echo "  import          Restore local DB from Nextcloud archive"
        echo "  pull --host X   Live SSH pull from remote host X"
        echo ""
        echo "See docs/SETUP.md for full documentation."
        ;;
    *) err "Unknown subcommand: ${SUBCOMMAND}. Use export, import, or pull." ;;
esac
