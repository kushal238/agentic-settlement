#!/usr/bin/env bash
# Start facilitator (:8001), API server (:8000), and frontend (:5173) together.
# Press Ctrl+C to stop all three.

set -e
cd "$(dirname "$0")"

export BFT_F=1
export GENESIS_ACCOUNTS_PATH=genesis.json

RED='\033[0;31m'; CYAN='\033[0;36m'; YELLOW='\033[0;33m'; GREEN='\033[0;32m'; NC='\033[0m'

log() { echo -e "${1}[${2}]${NC} ${3}"; }

python -m src.facilitator_server.main 2>&1 | sed "s/^/$(printf "${CYAN}[facilitator]${NC} ")/" &
FACILITATOR_PID=$!

python -m src.api_server.main 2>&1 | sed "s/^/$(printf "${YELLOW}[api]${NC} ")/" &
API_PID=$!

(cd frontend && npm run dev) 2>&1 | sed "s/^/$(printf "${GREEN}[frontend]${NC} ")/" &
FRONTEND_PID=$!

cleanup() {
  echo ""
  log "$RED" "shutdown" "stopping all services…"
  kill "$FACILITATOR_PID" "$API_PID" "$FRONTEND_PID" 2>/dev/null
  wait 2>/dev/null
  exit 0
}
trap cleanup INT TERM

log "$CYAN"   "facilitator" "started (pid $FACILITATOR_PID)"
log "$YELLOW" "api"         "started (pid $API_PID)"
log "$GREEN"  "frontend"    "started (pid $FRONTEND_PID)"
echo ""
echo "  facilitator → http://localhost:8001"
echo "  api server  → http://localhost:8000"
echo "  frontend    → http://localhost:5173"
echo ""
echo "  Press Ctrl+C to stop all."

wait
