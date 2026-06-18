#!/usr/bin/env bash
# ── PDF2LaTeX — Development launcher ────────────────────────────────────
# Starts backend (FastAPI + uvicorn) and frontend (Vite) together.
# Usage:  bash dev.sh
# Stop:   Ctrl+C  (cleans up both processes)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Colours ─────────────────────────────────────────────────────────────
BOLD="\033[1m"
GREEN="\033[32m"
BLUE="\033[34m"
RESET="\033[0m"

_cleaned=false
cleanup() {
    $_cleaned && return
    _cleaned=true
    echo ""
    echo -e "${BOLD}Shutting down…${RESET}"
    kill "$BACKEND_PID" 2>/dev/null || true
    kill "$FRONTEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
    wait "$FRONTEND_PID" 2>/dev/null || true
    echo -e "${GREEN}Done.${RESET}"
}
trap cleanup SIGINT SIGTERM EXIT

# ── Backend ─────────────────────────────────────────────────────────────
echo -e "${BOLD}${BLUE}▶ Backend${RESET}  starting on ${BOLD}http://localhost:8000${RESET} …"
cd "$SCRIPT_DIR/backend"
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Give the backend a moment to start before launching the frontend.
# Wait for the backend to become reachable (max 15 s).
echo -ne "  Waiting for backend "
for _ in $(seq 1 30); do
    if curl -s http://localhost:8000/api/health >/dev/null 2>&1; then
        echo -e " ${GREEN}ready${RESET}"
        break
    fi
    echo -n "."
    sleep 0.5
done
if ! curl -s http://localhost:8000/api/health >/dev/null 2>&1; then
    echo ""
    echo -e "${BOLD}⚠ Backend did not respond in time — starting frontend anyway.${RESET}"
fi

# ── Frontend ────────────────────────────────────────────────────────────
echo -e "${BOLD}${GREEN}▶ Frontend${RESET} starting on ${BOLD}http://localhost:5173${RESET} …"
cd "$SCRIPT_DIR/frontend"
bun run dev &
FRONTEND_PID=$!

# ── Ready ───────────────────────────────────────────────────────────────
echo ""
echo -e "  ${BOLD}Backend${RESET}   → ${BLUE}http://localhost:8000${RESET}"
echo -e "  ${BOLD}Frontend${RESET}  → ${GREEN}http://localhost:5173${RESET}"
echo -e "  ${BOLD}API docs${RESET}  → ${BLUE}http://localhost:8000/docs${RESET}"
echo ""
echo -e "Press ${BOLD}Ctrl+C${RESET} to stop both services."
echo ""

wait
