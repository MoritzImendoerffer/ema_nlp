#!/usr/bin/env bash
# sync_mongo.sh — synchronise the ema_scraper MongoDB database between machines.
#
# SUBCOMMANDS
#   export   Dump the local database to ~/Nextcloud/Datasets/db_sync/mongo.archive.gz
#            (Nextcloud then syncs the file to other machines automatically)
#
#   import   Restore the local database from the Nextcloud archive
#            (run after Nextcloud has finished syncing on this machine)
#
#   pull     Live one-way pull via SSH + Tailscale (both machines must be on)
#            scripts/sync_mongo.sh pull --host <tailscale-ip> [--user <user>]
#
# FLAGS
#   --yes            Suppress confirm-before-drop (for wrapper / scripted use)
#   --skip-checksum  On import: skip sha256 verification (use only when the
#                    wrapper has already verified)
#
# Archive path changed in DBSYNC-004:
#   OLD: ~/Nextcloud/Datasets/mongo_sync/ema_scraper.archive   (uncompressed)
#   NEW: ~/Nextcloud/Datasets/db_sync/mongo.archive.gz         (gzipped)
# The script detects the legacy path on export/import and prints a one-time
# deprecation note. It does NOT auto-migrate the file content — the formats
# are not interchangeable. To migrate: re-run `export` on the source machine.
#
# CREDENTIALS
#   No credentials are stored in this script or the repository.
#   Optional env vars (loaded from ~/.myenvs/ema_nlp.env if present):
#     NEXTCLOUD_DATASETS   path to Nextcloud datasets folder (default: ~/Nextcloud/Datasets)
#     MONGO_URI            local MongoDB URI (default: mongodb://localhost:27017/)
#     STORAGE_BACKEND      default: nextcloud (see scripts/lib/_artifact_store.sh)
#     MONGO_SYNC_HOST      remote host for 'pull' subcommand
#     MONGO_SYNC_USER      SSH user for 'pull' subcommand (default: $USER)
#     MONGO_SYNC_SSH_PORT  SSH port for 'pull' subcommand (default: 22)
#     EMA_DBSYNC_WRAPPER   set to 1 by sync_databases.sh

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# shellcheck source=scripts/lib/_artifact_store.sh
source "${SCRIPT_DIR}/lib/_artifact_store.sh"
# shellcheck source=scripts/lib/_manifest.sh
source "${SCRIPT_DIR}/lib/_manifest.sh"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[ok]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*" >&2; }
err()  { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

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
ARCHIVE_NAME="mongo.archive.gz"
LEGACY_ARCHIVE="${NX_DATASETS}/mongo_sync/ema_scraper.archive"

# SSH pull defaults (only used by 'pull' subcommand)
REMOTE_HOST="${MONGO_SYNC_HOST:-}"
REMOTE_USER="${MONGO_SYNC_USER:-$USER}"
REMOTE_PORT="${MONGO_SYNC_SSH_PORT:-22}"

# Flags (parsed below).
YES_FLAG=0
SKIP_CHECKSUM=0

# ── Helpers ───────────────────────────────────────────────────────────────────
require_cmd() {
    command -v "$1" &>/dev/null || err "$1 not found. ${2:-Install mongodb-database-tools.}"
}

confirm_drop() {
    if [ "$YES_FLAG" = "1" ]; then
        echo "[!] --yes set: skipping confirm-before-drop prompt."
        return 0
    fi
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

# Returns JSON object of key collection counts; tolerates missing collections.
local_counts_json() {
    require_cmd mongosh "Install mongodb-mongosh."
    local script
    script=$(cat <<'EOF'
        const d = db.getSiblingDB("ema_scraper");
        const collections = d.getCollectionNames();
        const out = {};
        for (const name of ["web_items", "parsed_pdfs", "parsed_documents", "link_graph"]) {
            out[name] = collections.includes(name) ? d.getCollection(name).countDocuments() : 0;
        }
        print(JSON.stringify(out));
EOF
)
    mongosh --quiet --uri "${LOCAL_MONGO_URI}" --eval "$script" 2>/dev/null || echo "{}"
}

manifest_path() {
    local base; base=$(_artifact_base_dir)
    echo "${base}/${ARCHIVE_NAME}.manifest.json"
}

deprecation_check() {
    # Inform the user that a legacy archive sits at the old path. No file ops.
    if [ -f "$LEGACY_ARCHIVE" ]; then
        warn "Legacy archive detected at ${LEGACY_ARCHIVE}."
        warn "  This file is in the old uncompressed format and will NOT be used."
        warn "  To migrate: re-run \`sync_mongo.sh export\` on the source machine — the new"
        warn "  archive is written to ${NX_DATASETS}/db_sync/${ARCHIVE_NAME} (gzipped)."
        warn "  Once you've confirmed the new workflow works, you can delete the legacy file."
    fi
}

# ── Subcommand: export ────────────────────────────────────────────────────────
cmd_export() {
    require_cmd mongodump "Install mongodb-database-tools."
    require_cmd jq "Install: sudo apt install jq"
    require_cmd sha256sum "Install: sudo apt install coreutils"

    echo ""
    echo "=== MongoDB export → ${STORAGE_BACKEND:-nextcloud} ==="
    echo "  Source : ${LOCAL_MONGO_URI} / ${DB_NAME}"
    echo "  Archive: ${ARCHIVE_NAME} (gzipped)"
    echo ""

    deprecation_check

    local counts; counts=$(local_counts_json)
    echo "  Local counts: $(echo "$counts" | jq -c .)"
    echo ""

    if [ "$YES_FLAG" != "1" ]; then
        read -r -p "Export now? [Y/n] " CONFIRM
        [[ "${CONFIRM:-Y}" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
    fi

    local tmp_archive; tmp_archive=$(mktemp -t mongo_archive.XXXXXX.gz)
    # shellcheck disable=SC2064
    trap "rm -f '$tmp_archive'" EXIT INT TERM

    local start end; start=$(date +%s)
    mongodump --uri "${LOCAL_MONGO_URI}" --db "${DB_NAME}" --gzip --archive="${tmp_archive}" \
        || err "mongodump failed"
    end=$(date +%s)

    local size sha
    size=$(stat -c '%s' "$tmp_archive")
    sha=$(sha256sum "$tmp_archive" | awk '{print $1}')

    _put_artifact "$tmp_archive" "$ARCHIVE_NAME" || err "_put_artifact failed"

    # Per-DB manifest fragment alongside the archive.
    local mp; mp=$(manifest_path)
    _manifest_init "$mp"                                              || err "_manifest_init failed"
    _manifest_add_db "$mp" mongo "$ARCHIVE_NAME" "$size" "$sha" "$DB_NAME" "$counts" \
        || err "_manifest_add_db failed"
    _manifest_finalize "$mp"                                          || err "_manifest_finalize failed"

    local human_size; human_size=$(du -h "$(_artifact_base_dir)/${ARCHIVE_NAME}" | cut -f1)
    ok "Export complete in $(( end - start ))s — ${human_size} (${size} bytes), sha256 ${sha:0:12}…"
}

# ── Subcommand: import ────────────────────────────────────────────────────────
cmd_import() {
    require_cmd mongorestore "Install mongodb-database-tools."
    require_cmd jq "Install: sudo apt install jq"

    deprecation_check

    _artifact_exists "$ARCHIVE_NAME" \
        || err "Archive '$ARCHIVE_NAME' not found in artifact store. Run 'sync_mongo.sh export' on the source machine first and wait for Nextcloud to sync."

    local tmp_archive; tmp_archive=$(mktemp -t mongo_archive.XXXXXX.gz)
    # shellcheck disable=SC2064
    trap "rm -f '$tmp_archive'" EXIT INT TERM

    _get_artifact "$ARCHIVE_NAME" "$tmp_archive" || err "_get_artifact failed"

    local mp; mp=$(manifest_path)
    if [ "$SKIP_CHECKSUM" != "1" ] && [ -f "$mp" ]; then
        _manifest_verify_archive "$mp" mongo "$tmp_archive" \
            || err "Refusing to import — sha256 mismatch. Likely a partial Nextcloud upload; wait and retry."
    fi

    echo ""
    echo "=== MongoDB import ← ${STORAGE_BACKEND:-nextcloud} ==="
    echo "  Archive    : ${ARCHIVE_NAME}"
    echo "  Target     : ${LOCAL_MONGO_URI} / ${DB_NAME}"
    if [ -f "$mp" ]; then
        echo "  Source host: $(jq -r '.source_host // "unknown"' "$mp")"
        echo "  Exported at: $(jq -r '.exported_at // "unknown"' "$mp")"
        echo "  Archive sha: $(jq -r '.mongo.sha256 // "?"' "$mp" | cut -c1-12)…"
    fi

    local size; size=$(stat -c '%s' "$tmp_archive")
    echo "  Archive size : ${size} bytes"

    confirm_drop

    local start end; start=$(date +%s)
    mongorestore --drop --gzip --archive="${tmp_archive}" --db "${DB_NAME}" --uri "${LOCAL_MONGO_URI}" \
        || err "mongorestore failed"
    end=$(date +%s)

    local count; count=$(local_count)
    ok "Import complete in $(( end - start ))s — local web_items count: ${count}"
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

    require_cmd mongorestore "Install mongodb-database-tools."
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

    local remote_count
    remote_count=$(ssh -p "$REMOTE_PORT" "${REMOTE_USER}@${REMOTE_HOST}" \
        "mongosh --quiet --eval 'db.getSiblingDB(\"${DB_NAME}\").web_items.countDocuments()'" \
        2>/dev/null || echo "unknown")
    echo "  Remote web_items count: ${remote_count}"

    confirm_drop

    local start end; start=$(date +%s)
    ssh -p "$REMOTE_PORT" "${REMOTE_USER}@${REMOTE_HOST}" \
        "mongodump --db ${DB_NAME} --gzip --archive" \
      | mongorestore --drop --gzip --archive --db "${DB_NAME}" --uri "${LOCAL_MONGO_URI}" \
      || err "pull pipeline failed"
    end=$(date +%s)

    local local_count_val; local_count_val=$(local_count)
    ok "Pull complete in $(( end - start ))s."
    echo "  Remote count : ${remote_count}"
    echo "  Local count  : ${local_count_val}"
}

# ── Dispatch ──────────────────────────────────────────────────────────────────
print_help() {
    cat <<'EOF'
Usage: sync_mongo.sh <subcommand> [flags]

Subcommands:
  export             Dump local DB to Nextcloud archive
  import             Restore local DB from Nextcloud archive
  pull --host X      Live SSH pull from remote host X

Flags:
  --yes              Suppress confirm-before-drop prompts (for scripted use)
  --skip-checksum    On import: skip sha256 verification

See docs/SYNC.md (DBSYNC-009 — pending) for the full workflow.
EOF
}

SUBCOMMAND="${1:-}"
shift || true

# Collect pull-specific flags separately so cmd_pull parses them itself.
PULL_ARGS=()
if [ "${SUBCOMMAND}" = "pull" ]; then
    # Pull's --host/--user/--port flags take values; pass everything through.
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --yes)            YES_FLAG=1;       shift ;;
            --skip-checksum)  SKIP_CHECKSUM=1;  shift ;;
            *)                PULL_ARGS+=("$1"); shift ;;
        esac
    done
else
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --yes)            YES_FLAG=1;       shift ;;
            --skip-checksum)  SKIP_CHECKSUM=1;  shift ;;
            --help|-h)        print_help; exit 0 ;;
            *)                err "Unknown flag: $1 (run sync_mongo.sh --help)" ;;
        esac
    done
fi

case "$SUBCOMMAND" in
    export)        cmd_export ;;
    import)        cmd_import ;;
    pull)          cmd_pull "${PULL_ARGS[@]:-}" ;;
    ""|--help|-h)  print_help ;;
    *)             err "Unknown subcommand: ${SUBCOMMAND}. Use export, import, or pull." ;;
esac
