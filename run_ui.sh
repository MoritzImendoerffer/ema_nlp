#!/usr/bin/env bash
# run_ui.sh — start the MLflow tracking server + Chainlit chat UI
#
# The MLflow server is the trace store + HITL feedback surface (it replaced Arize
# Phoenix). The Chainlit app logs each turn as an MLflow trace and writes 👍/👎 as
# trace assessments; both are viewed in the MLflow UI.
#
# Usage:
#   ./run_ui.sh                          # MLflow on :5000, Chainlit on :8000
#   EMA_TRACING_DISABLED=1 ./run_ui.sh   # Chainlit only, no tracing/feedback

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MLFLOW_PORT="${MLFLOW_PORT:-5000}"
CHAINLIT_PORT="${CHAINLIT_PORT:-8000}"
TRACING_DISABLED="${EMA_TRACING_DISABLED:-}"
# sqlite backend: required for trace assessments (👍/👎). The local file store
# cannot persist assessments — see harness/obs/tracing.py.
MLFLOW_BACKEND_URI="${MLFLOW_BACKEND_URI:-sqlite:///${REPO_ROOT}/mlflow.db}"
MLFLOW_ARTIFACTS="${MLFLOW_ARTIFACTS:-${REPO_ROOT}/mlartifacts}"

# Prefer the project virtualenv's binaries so this works regardless of which
# environment is active. Launching from a conda `base` shell (the common case)
# leaves .venv off PATH, so `mlflow`/`chainlit` resolve to "command not found".
if [[ -d "${REPO_ROOT}/.venv/bin" ]]; then
    export PATH="${REPO_ROOT}/.venv/bin:${PATH}"
fi

# The app logs traces/feedback to this server; the same server serves the UI.
export MLFLOW_TRACKING_URI="${MLFLOW_TRACKING_URI:-http://localhost:${MLFLOW_PORT}}"
export MLFLOW_UI_URL="${MLFLOW_UI_URL:-http://localhost:${MLFLOW_PORT}}"

MLFLOW_PID=""

cleanup() {
    if [[ -n "$MLFLOW_PID" ]]; then
        echo ""
        echo "Stopping MLflow server (pid $MLFLOW_PID)…"
        kill "$MLFLOW_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

cd "$REPO_ROOT"

# ── MLflow tracking server ────────────────────────────────────────────────────
if [[ -z "$TRACING_DISABLED" ]]; then
    if curl -sf "http://localhost:${MLFLOW_PORT}/health" >/dev/null 2>&1; then
        echo "MLflow already running on :${MLFLOW_PORT}"
    else
        echo "Starting MLflow server on :${MLFLOW_PORT} (backend ${MLFLOW_BACKEND_URI})…"
        mlflow server \
            --backend-store-uri "$MLFLOW_BACKEND_URI" \
            --artifacts-destination "$MLFLOW_ARTIFACTS" \
            --host 127.0.0.1 --port "$MLFLOW_PORT" \
            >"${REPO_ROOT}/.mlflow.log" 2>&1 &
        MLFLOW_PID=$!

        # Wait up to 30 s for the server to be ready (it builds the DB on first run).
        for i in $(seq 1 30); do
            if curl -sf "http://localhost:${MLFLOW_PORT}/health" >/dev/null 2>&1; then
                echo "MLflow ready → http://localhost:${MLFLOW_PORT}"
                break
            fi
            if ! kill -0 "$MLFLOW_PID" 2>/dev/null; then
                echo "MLflow failed to start. Log:" >&2
                cat "${REPO_ROOT}/.mlflow.log" >&2
                exit 1
            fi
            sleep 1
        done
    fi
else
    echo "EMA_TRACING_DISABLED=1 — skipping MLflow"
fi

# ── Chainlit ──────────────────────────────────────────────────────────────────
echo "Starting Chainlit on :${CHAINLIT_PORT}…"
echo "Chat UI → http://localhost:${CHAINLIT_PORT}"
echo ""

chainlit run app.py --port "$CHAINLIT_PORT"
