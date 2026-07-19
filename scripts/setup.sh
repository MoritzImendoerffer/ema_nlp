#!/usr/bin/env bash
# setup.sh — bootstrap ema_nlp on a new machine
#
# What this script does:
#   1. Checks runtime dependencies (Node.js, Python 3.11+, uv/pip)
#   2. Installs Claude Code (npm global) if missing
#   3. Installs Python project deps (pip install -e ".[dev]")
#   4. Optionally clones the claude-code-toolkit plugin repo
#   5. Guides you through creating the ema_nlp.env file
#
# Credentials are NEVER stored in this repo.
# All secrets go in ~/Nextcloud/Datasets/ema_nlp/ema_nlp.env (created interactively below).

set -euo pipefail

# uv installs to ~/.local/bin (Linux/macOS) or ~/.cargo/bin — add both so
# command -v uv works in non-interactive shells that don't source ~/.bashrc.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[ok]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
err()  { echo -e "${RED}[error]${NC} $*"; exit 1; }
ask()  { echo -e "${YELLOW}[?]${NC} $*"; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo ""
echo "=== ema_nlp setup ==="
echo "Repo: $REPO_ROOT"
echo ""

# ── 1. Node.js ────────────────────────────────────────────────────────────────
if ! command -v node &>/dev/null; then
    err "Node.js not found. Install it from https://nodejs.org (v18+) and re-run."
fi
NODE_VERSION=$(node --version | tr -d 'v' | cut -d. -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    err "Node.js v18+ required (found v${NODE_VERSION}). Please upgrade."
fi
ok "Node.js $(node --version)"

# ── 2. Python 3.11+ ───────────────────────────────────────────────────────────
PYTHON=""
for cmd in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" -c "import sys; print(sys.version_info >= (3,11))" 2>/dev/null || echo False)
        if [ "$VER" = "True" ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done
[ -n "$PYTHON" ] || err "Python 3.11+ not found. Install it and re-run."
ok "Python $($PYTHON --version)"

# ── 3. uv (install if missing) ────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    ask "uv not found. Install it now via the official installer? [Y/n]"
    read -r REPLY
    if [[ "${REPLY:-Y}" =~ ^[Yy]$ ]]; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
        command -v uv &>/dev/null || err "uv install succeeded but still not found — open a new shell and re-run."
        ok "uv installed: $(uv --version)"
    else
        err "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/ and re-run."
    fi
fi
ok "uv $(uv --version | awk '{print $2}')"

# ── 4. virtualenv ─────────────────────────────────────────────────────────────
VENV_DIR="${REPO_ROOT}/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR ..."
    uv venv "$VENV_DIR"
else
    ok "Virtual environment already exists at $VENV_DIR"
fi
INSTALL_CMD="uv pip install --python \"${VENV_DIR}\" -e \"${REPO_ROOT}[dev]\""

# ── 5. Claude Code ────────────────────────────────────────────────────────────
if command -v claude &>/dev/null; then
    ok "Claude Code $(claude --version 2>/dev/null | head -1)"
else
    ask "Claude Code not found. Install it now? [Y/n]"
    read -r REPLY
    if [[ "${REPLY:-Y}" =~ ^[Yy]$ ]]; then
        npm install -g @anthropic-ai/claude-code
        ok "Claude Code installed."
    else
        warn "Skipped. Install later with: npm install -g @anthropic-ai/claude-code"
    fi
fi

# ── 6. Python deps ────────────────────────────────────────────────────────────
echo ""
echo "Installing Python project dependencies..."
eval "$INSTALL_CMD"
ok "Python deps installed."

# ── 7. claude-code-toolkit plugins ───────────────────────────────────────────
EXPECTED_TOOLKIT_PATH="$HOME/github_repos/claude-code-toolkit"
TOOLKIT_REPO="https://github.com/MoritzImendoerffer/claude-code-toolkit"

echo ""
if [ -d "$EXPECTED_TOOLKIT_PATH" ]; then
    ok "claude-code-toolkit found at $EXPECTED_TOOLKIT_PATH"
else
    ask "claude-code-toolkit not found at $EXPECTED_TOOLKIT_PATH."
    ask "Clone it now (needed for custom Claude Code plugins/skills)? [Y/n]"
    read -r REPLY
    if [[ "${REPLY:-Y}" =~ ^[Yy]$ ]]; then
        mkdir -p "$(dirname "$EXPECTED_TOOLKIT_PATH")"
        git clone "$TOOLKIT_REPO" "$EXPECTED_TOOLKIT_PATH"
        ok "claude-code-toolkit cloned."
    else
        warn "Skipped. Custom plugins will not be available in Claude Code."
        warn "If your toolkit is elsewhere, update .claude/settings.json manually."
    fi
fi

# Register the local marketplace and enable plugins in ~/.claude/settings.json
# Uses Python (already verified above) so we don't require jq.
GLOBAL_SETTINGS="$HOME/.claude/settings.json"
mkdir -p "$HOME/.claude"
"$PYTHON" - <<PYEOF
import json, os, sys

path = os.path.expanduser("$GLOBAL_SETTINGS")
toolkit = os.path.expanduser("$EXPECTED_TOOLKIT_PATH")

cfg = {}
if os.path.exists(path):
    with open(path) as f:
        cfg = json.load(f)

# Register local marketplace
cfg.setdefault("extraKnownMarketplaces", {}).setdefault("local", {
    "source": {"source": "directory", "path": f"{toolkit}/plugins"}
})

# Enable core local plugins and official marketplace plugins
plugins = cfg.setdefault("enabledPlugins", {})
for p in [
    "system@local", "workflow@local", "memory@local",
    "development@local", "transition@local",
    "mongodb@claude-plugins-official",
    "github@claude-plugins-official",
    "session-report@claude-plugins-official",
]:
    plugins.setdefault(p, True)

with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
print(f"  configured {path}")
PYEOF
ok "~/.claude/settings.json updated with local marketplace."

# ── 8. MCP servers ────────────────────────────────────────────────────────────
# context7 and serena run on-demand via npx/uvx — just register them.
echo ""
echo "Registering MCP servers..."

register_mcp() {
    local name="$1"; shift
    if claude mcp list 2>/dev/null | grep -q "^${name}:"; then
        ok "MCP: ${name} already registered"
    else
        if claude mcp add "$@" 2>/dev/null; then
            ok "MCP: ${name} registered"
        else
            warn "MCP: failed to register ${name} — run manually: claude mcp add $*"
        fi
    fi
}

register_mcp "context7"  context7  -- npx -y @upstash/context7-mcp
register_mcp "serena"    serena    -- uvx --from git+https://github.com/oraios/serena serena start-mcp-server

warn "MCP: Gmail / Google Drive / Google Calendar require browser authentication."
warn "      Run 'claude' and authenticate those connectors on first use."

# ── 9. ema_nlp.env (canonical: ~/Nextcloud/Datasets/ema_nlp/) ────────────────
# config.py searches: $EMA_ENV_FILE → ~/Nextcloud/Datasets/ema_nlp/ema_nlp.env
# → ~/.myenvs/ema_nlp.env (legacy). New files are created at the canonical path.
ENV_FILE="${EMA_ENV_FILE:-$HOME/Nextcloud/Datasets/ema_nlp/ema_nlp.env}"
LEGACY_ENV_FILE="$HOME/.myenvs/ema_nlp.env"
if [ ! -f "$ENV_FILE" ] && [ -f "$LEGACY_ENV_FILE" ]; then
    ok "Using legacy env file: $LEGACY_ENV_FILE (canonical location is $ENV_FILE)"
    ENV_FILE="$LEGACY_ENV_FILE"
fi
echo ""
if [ -f "$ENV_FILE" ]; then
    ok "Env file already exists: $ENV_FILE"
else
    ask "Env file not found at $ENV_FILE. Create it now? [Y/n]"
    read -r REPLY
    if [[ "${REPLY:-Y}" =~ ^[Yy]$ ]]; then
        mkdir -p "$(dirname "$ENV_FILE")"

        ask "Enter your Anthropic API key (sk-ant-...): "
        read -r API_KEY

        cat > "$ENV_FILE" <<EOF
# ema_nlp environment — machine-specific, never commit this file.

ANTHROPIC_API_KEY=${API_KEY}

# MongoDB URI for this machine (default is localhost:27017).
# On the laptop, leave this as localhost after running scripts/sync_mongo.sh.
# MONGO_URI=mongodb://localhost:27017/
EOF
        chmod 600 "$ENV_FILE"
        ok "Created $ENV_FILE (permissions: 600)"
    else
        warn "Skipped. config.py will fall back to environment variables and defaults."
        warn "Create $ENV_FILE later — see scripts/setup.sh for the required variables."
    fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Activate the venv:         source $REPO_ROOT/.venv/bin/activate"
echo "  2. Authenticate Claude Code:  claude  (first run opens a browser)"
echo "  3. Run tests:                 cd $REPO_ROOT && pytest"
echo "  4. Start a session:           cd $REPO_ROOT && claude"
echo ""
echo "To sync MongoDB from your PC to this machine (one-time, on demand):"
echo "  scripts/sync_mongo.sh --host <tailscale-ip-or-hostname> --user <ssh-user>"
echo ""
