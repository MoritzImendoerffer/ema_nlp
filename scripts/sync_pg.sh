#!/usr/bin/env bash
# sync_pg.sh — synchronise the ema_nlp Postgres database between machines.
#
# Symmetric to scripts/sync_mongo.sh. All PG access goes through `docker exec`
# against the ema_nlp_pg container, so the host needs no PG client install.
#
# SUBCOMMANDS
#   export   Dump the local DB to ~/Nextcloud/Datasets/db_sync/pg.dump
#            (Nextcloud then syncs the file to other machines automatically)
#
#   import   Restore the local DB from the Nextcloud archive
#            (run after Nextcloud has finished syncing on this machine)
#
#   pull     Live one-way pull via SSH + Tailscale  [DBSYNC-007 — not yet wired]
#
# FLAGS
#   --yes            Suppress confirm-before-drop (for wrapper / scripted use)
#   --no-embeddings  On export: exclude `chunks` table data (schema kept).
#                    The receiver rebuilds chunks via `python -m harness.embed_pg`.
#   --skip-checksum  On import: skip sha256 verification (use only when the
#                    wrapper has already verified).
#
# ENV (loaded from ~/.myenvs/ema_nlp.env if present):
#   NEXTCLOUD_DATASETS   path to Nextcloud datasets folder (default: ~/Nextcloud/Datasets)
#   POSTGRES_USER        default: ema_nlp
#   POSTGRES_DB          default: ema_nlp
#   PG_CONTAINER         default: ema_nlp_pg
#   STORAGE_BACKEND      default: nextcloud (see scripts/lib/_artifact_store.sh)
#   EMA_DBSYNC_WRAPPER   set to 1 by sync_databases.sh; per-DB script then writes
#                        a per-archive manifest fragment for the wrapper to merge.

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
POSTGRES_USER="${POSTGRES_USER:-ema_nlp}"
POSTGRES_DB="${POSTGRES_DB:-ema_nlp}"
PG_CONTAINER="${PG_CONTAINER:-ema_nlp_pg}"
ARCHIVE_NAME="pg.dump"

# Flags (parsed below).
YES_FLAG=0
NO_EMBEDDINGS=0
SKIP_CHECKSUM=0

# ── Helpers ───────────────────────────────────────────────────────────────────
require_cmd() {
    command -v "$1" &>/dev/null || err "$1 not found. ${2:-Install it and retry.}"
}

require_pg_container() {
    if ! docker ps --filter "name=^${PG_CONTAINER}$" --filter "status=running" --format '{{.Names}}' \
            | grep -q "^${PG_CONTAINER}$"; then
        err "Postgres container '${PG_CONTAINER}' is not running. Start with: scripts/start_services.sh"
    fi
}

pg_psql() {
    # Run a one-shot SQL query, return the bare value.
    docker exec "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -tAc "$1" 2>/dev/null
}

# Returns a JSON object {documents, chunks, links} for the local DB. Falls back
# to zeros if a table doesn't exist (e.g. fresh DB pre-init).
local_counts_json() {
    local docs chunks links
    docs=$(pg_psql "SELECT COUNT(*) FROM documents" 2>/dev/null || echo 0)
    chunks=$(pg_psql "SELECT COUNT(*) FROM chunks"    2>/dev/null || echo 0)
    links=$(pg_psql "SELECT COUNT(*) FROM links"      2>/dev/null || echo 0)
    docs="${docs:-0}"; chunks="${chunks:-0}"; links="${links:-0}"
    jq -n --argjson d "$docs" --argjson c "$chunks" --argjson l "$links" \
        '{documents: $d, chunks: $c, links: $l}'
}

confirm_drop() {
    if [ "$YES_FLAG" = "1" ]; then
        echo "[!] --yes set: skipping confirm-before-drop prompt."
        return 0
    fi
    echo ""
    echo -e "${YELLOW}[!]${NC} This will DROP all data in '${POSTGRES_DB}' and replace it."
    read -r -p "    Continue? [y/N] " CONFIRM
    [[ "${CONFIRM:-N}" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
}

manifest_path() {
    # Per-DB manifest sits next to the archive when standalone; the wrapper
    # writes the combined manifest.json itself.
    local base; base=$(_artifact_base_dir)
    if [ "${EMA_DBSYNC_WRAPPER:-0}" = "1" ]; then
        echo "${base}/${ARCHIVE_NAME}.manifest.json"
    else
        echo "${base}/${ARCHIVE_NAME}.manifest.json"
    fi
}

# ── Subcommand: export ────────────────────────────────────────────────────────
cmd_export() {
    require_cmd docker "Install Docker."
    require_cmd jq "Install: sudo apt install jq"
    require_pg_container

    local mode_note=""
    [ "$NO_EMBEDDINGS" = "1" ] && mode_note=" (mode: --no-embeddings)"

    echo ""
    echo "=== Postgres export → ${STORAGE_BACKEND:-nextcloud}${mode_note} ==="
    echo "  Source  : ${PG_CONTAINER} / ${POSTGRES_DB} (user ${POSTGRES_USER})"
    echo "  Archive : ${ARCHIVE_NAME}"
    echo ""

    local counts; counts=$(local_counts_json)
    echo "  Local counts: $(echo "$counts" | jq -c .)"
    echo ""

    if [ "$YES_FLAG" != "1" ]; then
        read -r -p "Export now? [Y/n] " CONFIRM
        [[ "${CONFIRM:-Y}" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
    fi

    # Build pg_dump argv.
    local dump_args=(pg_dump --format=custom --compress=6 --no-owner --no-privileges \
                     -U "${POSTGRES_USER}" -d "${POSTGRES_DB}")
    if [ "$NO_EMBEDDINGS" = "1" ]; then
        dump_args+=(--exclude-table-data=chunks)
    fi

    local tmp_dump; tmp_dump=$(mktemp -t pg_dump.XXXXXX.dump)
    # shellcheck disable=SC2064
    trap "rm -f '$tmp_dump'" EXIT INT TERM

    local start end; start=$(date +%s)
    if ! docker exec "${PG_CONTAINER}" "${dump_args[@]}" > "$tmp_dump"; then
        err "pg_dump failed (see container logs)"
    fi
    end=$(date +%s)

    local size sha
    size=$(stat -c '%s' "$tmp_dump")
    sha=$(sha256sum "$tmp_dump" | awk '{print $1}')

    _put_artifact "$tmp_dump" "$ARCHIVE_NAME" || err "_put_artifact failed"

    # Per-DB manifest fragment alongside the archive.
    local mp; mp=$(manifest_path)
    _manifest_init "$mp" || err "_manifest_init failed"
    _manifest_add_db "$mp" postgres "$ARCHIVE_NAME" "$size" "$sha" "$POSTGRES_DB" "$counts" \
        || err "_manifest_add_db failed"
    if [ "$NO_EMBEDDINGS" = "1" ]; then
        _manifest_set "$mp" ".postgres.embeddings_excluded" "true" \
            || err "_manifest_set failed"
    fi
    _manifest_finalize "$mp" || err "_manifest_finalize failed"

    local human_size; human_size=$(du -h "$(_artifact_base_dir)/${ARCHIVE_NAME}" | cut -f1)
    ok "Export complete in $(( end - start ))s — ${human_size} (${size} bytes), sha256 ${sha:0:12}…"
}

# ── Subcommand: import ────────────────────────────────────────────────────────
cmd_import() {
    require_cmd docker "Install Docker."
    require_cmd jq "Install: sudo apt install jq"
    require_pg_container

    _artifact_exists "$ARCHIVE_NAME" \
        || err "Archive '$ARCHIVE_NAME' not found in artifact store. Run 'sync_pg.sh export' on the source machine first and wait for Nextcloud to sync."

    local tmp_dump; tmp_dump=$(mktemp -t pg_dump.XXXXXX.dump)
    # shellcheck disable=SC2064
    trap "rm -f '$tmp_dump'" EXIT INT TERM

    _get_artifact "$ARCHIVE_NAME" "$tmp_dump" || err "_get_artifact failed"

    local mp; mp=$(manifest_path)
    if [ "$SKIP_CHECKSUM" != "1" ] && [ -f "$mp" ]; then
        _manifest_verify_archive "$mp" postgres "$tmp_dump" \
            || err "Refusing to import — sha256 mismatch. Likely a partial Nextcloud upload; wait and retry."
    fi

    echo ""
    echo "=== Postgres import ← ${STORAGE_BACKEND:-nextcloud} ==="
    echo "  Archive    : ${ARCHIVE_NAME}"
    echo "  Target     : ${PG_CONTAINER} / ${POSTGRES_DB} (user ${POSTGRES_USER})"
    if [ -f "$mp" ]; then
        echo "  Source host: $(jq -r '.source_host // "unknown"' "$mp")"
        echo "  Exported at: $(jq -r '.exported_at // "unknown"' "$mp")"
        echo "  Archive sha: $(jq -r '.postgres.sha256 // "?"' "$mp" | cut -c1-12)…"
        local embeddings_excluded; embeddings_excluded=$(jq -r '.postgres.embeddings_excluded // false' "$mp")
        if [ "$embeddings_excluded" = "true" ]; then
            warn "Archive was exported with --no-embeddings (chunks table will be empty)."
        fi
    fi

    local current; current=$(local_counts_json)
    echo "  Local counts before: $(echo "$current" | jq -c .)"

    confirm_drop

    local start end; start=$(date +%s)
    if ! docker exec -i "${PG_CONTAINER}" pg_restore \
            --clean --if-exists --no-owner --no-privileges \
            -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" < "$tmp_dump"; then
        err "pg_restore failed — DB may be in a partial state. Re-run import after diagnosing, or wipe with: docker exec ${PG_CONTAINER} psql -U ${POSTGRES_USER} -d postgres -c 'DROP DATABASE ${POSTGRES_DB}; CREATE DATABASE ${POSTGRES_DB};'"
    fi
    end=$(date +%s)

    local new; new=$(local_counts_json)
    ok "Import complete in $(( end - start ))s — local counts: $(echo "$new" | jq -c .)"

    if [ -f "$mp" ]; then
        local embeddings_excluded; embeddings_excluded=$(jq -r '.postgres.embeddings_excluded // false' "$mp")
        if [ "$embeddings_excluded" = "true" ]; then
            echo ""
            warn "Chunks table is empty (--no-embeddings dump). To repopulate:"
            echo "       python -m harness.embed_pg"
        fi
    fi
}

# ── Subcommand: pull (placeholder for DBSYNC-007) ─────────────────────────────
cmd_pull() {
    err "sync_pg.sh pull is not yet wired (DBSYNC-007). For now, use export + import via Nextcloud."
}

# ── Dispatch ──────────────────────────────────────────────────────────────────
print_help() {
    cat <<'EOF'
Usage: sync_pg.sh <subcommand> [flags]

Subcommands:
  export             Dump local PG to Nextcloud archive
  import             Restore local PG from Nextcloud archive
  pull               Live SSH pull from a remote host  [DBSYNC-007 — not yet wired]

Flags:
  --yes              Suppress confirm-before-drop prompts (for scripted use)
  --no-embeddings    On export: exclude chunks table data (schema kept)
  --skip-checksum    On import: skip sha256 verification

See docs/SYNC.md for the full workflow (work-in-progress under DBSYNC-009).
EOF
}

SUBCOMMAND="${1:-}"
shift || true

# Parse flags before dispatch so the order doesn't matter.
while [[ ${#:-0} -gt 0 ]]; do
    case "$1" in
        --yes)            YES_FLAG=1;       shift ;;
        --no-embeddings)  NO_EMBEDDINGS=1;  shift ;;
        --skip-checksum)  SKIP_CHECKSUM=1;  shift ;;
        --help|-h)        print_help; exit 0 ;;
        *)                err "Unknown flag: $1 (run sync_pg.sh --help)" ;;
    esac
done

case "$SUBCOMMAND" in
    export)        cmd_export ;;
    import)        cmd_import ;;
    pull)          cmd_pull ;;
    ""|--help|-h)  print_help ;;
    *)             err "Unknown subcommand: ${SUBCOMMAND}. Use export, import, or pull." ;;
esac
