#!/usr/bin/env bash
# run_ui.sh — start Phoenix trace server + Chainlit chat UI
#
# Usage:
#   ./run_ui.sh              # Phoenix on :6006, Chainlit on :8000
#   PHOENIX_DISABLED=1 ./run_ui.sh   # Chainlit only, no tracing

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHOENIX_PORT="${PHOENIX_PORT:-6006}"
CHAINLIT_PORT="${CHAINLIT_PORT:-8000}"
PHOENIX_DISABLED="${PHOENIX_DISABLED:-}"

PHOENIX_PID=""

cleanup() {
    if [[ -n "$PHOENIX_PID" ]]; then
        echo ""
        echo "Stopping Phoenix (pid $PHOENIX_PID)…"
        kill "$PHOENIX_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

cd "$REPO_ROOT"

# ── Phoenix ───────────────────────────────────────────────────────────────────
if [[ -z "$PHOENIX_DISABLED" ]]; then
    if curl -sf "http://localhost:${PHOENIX_PORT}/healthz" >/dev/null 2>&1; then
        echo "Phoenix already running on :${PHOENIX_PORT}"
    else
        echo "Starting Phoenix on :${PHOENIX_PORT}…"
        PHOENIX_PORT="$PHOENIX_PORT" phoenix serve \
            >"${REPO_ROOT}/.phoenix.log" 2>&1 &
        PHOENIX_PID=$!

        # Wait up to 15 s for Phoenix to be ready
        for i in $(seq 1 15); do
            if curl -sf "http://localhost:${PHOENIX_PORT}/healthz" >/dev/null 2>&1; then
                echo "Phoenix ready → http://localhost:${PHOENIX_PORT}"
                break
            fi
            if ! kill -0 "$PHOENIX_PID" 2>/dev/null; then
                echo "Phoenix failed to start. Log:" >&2
                cat "${REPO_ROOT}/.phoenix.log" >&2
                exit 1
            fi
            sleep 1
        done
    fi
else
    echo "PHOENIX_DISABLED=1 — skipping Phoenix"
fi

# ── Chainlit ──────────────────────────────────────────────────────────────────
echo "Starting Chainlit on :${CHAINLIT_PORT}…"
echo "Chat UI → http://localhost:${CHAINLIT_PORT}"
echo ""

chainlit run app.py --port "$CHAINLIT_PORT"
