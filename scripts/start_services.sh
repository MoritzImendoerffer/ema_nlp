#!/usr/bin/env bash
# start_services.sh — bring up the local data services ema_nlp depends on.
#
# Services (LlamaIndex-first refactor — Postgres/pgvector dropped, see work unit 20):
#   1. MongoDB ema_scraper   (deploy/mongo)  — ingest source         -> :27017
#   2. Neo4j                 (deploy/neo4j)  — PropertyGraph store    -> :7687 / :7474
#
# Both run as Docker containers (see deploy/*/README.md). Mongo is pinned to
# image 8.0.4 to work around the kernel >= 6.19 incompatibility (SERVER-121912).
#
# Usage:
#   scripts/start_services.sh            # start + health-check both
#   scripts/start_services.sh --status   # report status, start nothing
#   scripts/start_services.sh --down     # stop + remove both containers

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[ok]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
err()  { echo -e "${RED}[error]${NC} $*" >&2; exit 1; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MONGO_DIR="${REPO_ROOT}/deploy/mongo"
NEO4J_DIR="${REPO_ROOT}/deploy/neo4j"

command -v docker >/dev/null 2>&1 || err "docker not found on PATH."
docker compose version >/dev/null 2>&1 || err "docker compose v2 not available."

MODE="${1:-up}"

# ── status / down short-circuits ──────────────────────────────────────────────
if [[ "$MODE" == "--status" ]]; then
    docker ps --filter name=ema_mongo --filter name=ema_neo4j \
        --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    exit 0
fi

if [[ "$MODE" == "--down" ]]; then
    ( cd "$NEO4J_DIR" && docker compose down ) || true
    ( cd "$MONGO_DIR" && docker compose down ) || true
    ok "Both services stopped."
    exit 0
fi

# ── helper: wait for a container's healthcheck to report healthy ───────────────
wait_healthy() {
    local name="$1" tries="${2:-30}"
    for _ in $(seq 1 "$tries"); do
        local s
        s="$(docker inspect --format '{{.State.Health.Status}}' "$name" 2>/dev/null || echo missing)"
        case "$s" in
            healthy) return 0 ;;
            missing) warn "container $name not found yet…" ;;
        esac
        sleep 2
    done
    return 1
}

echo ""
echo "=== ema_nlp services ==="
echo "Repo:   $REPO_ROOT"
echo "Kernel: $(uname -r)"
echo ""

# ── 1. MongoDB (ingest source) ────────────────────────────────────────────────
echo "── MongoDB (ema_scraper source) ──"
# Guard: a live native mongod would fight the container over /var/lib/mongodb.
if systemctl is-active --quiet mongod 2>/dev/null; then
    err "Native mongod is ACTIVE. It shares /var/lib/mongodb with the container.
       Stop it first (sudo systemctl stop mongod) or skip the container."
fi
( cd "$MONGO_DIR" && docker compose up -d )
if wait_healthy ema_mongo 30; then
    ok "MongoDB healthy on :${MONGO_PORT:-27017}"
    docker exec ema_mongo mongosh ema_scraper --quiet --eval \
        'print("       parsed_documents=" + db.parsed_documents.estimatedDocumentCount() +
               "  link_graph=" + db.link_graph.estimatedDocumentCount() +
               "  parsed_pdfs=" + db.parsed_pdfs.estimatedDocumentCount())' \
        2>/dev/null || warn "could not read ema_scraper collection counts"
else
    warn "MongoDB did not become healthy. Common cause on kernel >= 6.19:"
    warn "  the image tag drifted off 8.0.4. Check: docker logs ema_mongo"
    err  "MongoDB unhealthy — see deploy/mongo/README.md"
fi
echo ""

# ── 2. Neo4j (PropertyGraph store) ─────────────────────────────────────────────
echo "── Neo4j (PropertyGraph store) ──"
( cd "$NEO4J_DIR" && docker compose up -d )
if wait_healthy ema_neo4j 60; then
    ok "Neo4j healthy on bolt://localhost:7687 (browser :7474)"
else
    warn "Neo4j did not become healthy — check: docker logs ema_neo4j"
    err  "Neo4j unhealthy — see deploy/neo4j/README.md"
fi

echo ""
ok "All services up."
echo ""
echo "Next:"
echo "  Build index:  python -m harness.indexing.build --profile neo4j_hier   # (LIR-006/007)"
echo "  Chat UI:      ./run_ui.sh"
echo ""
