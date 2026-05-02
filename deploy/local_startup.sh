#!/bin/bash
# Local morning startup: Kite login + token exchange + start local services.
# Usage:
#   cd ~/algo_trading/ricky_1 && bash deploy/local_startup.sh

set -euo pipefail
trap 'echo -e "\033[0;31m[ERROR]\033[0m Startup failed at line $LINENO."' ERR

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENV_PY="$ROOT_DIR/venv/bin/python"
PYTHON_BIN="${PYTHON_BIN:-$VENV_PY}"
ALLOW_BASE_FALLBACK="${ALLOW_BASE_FALLBACK:-0}"

if [ ! -x "$VENV_PY" ]; then
    if [ "$ALLOW_BASE_FALLBACK" = "1" ] && command -v /opt/anaconda3/bin/python >/dev/null 2>&1; then
        warn "venv python missing, using Anaconda fallback due to ALLOW_BASE_FALLBACK=1"
        PYTHON_BIN="/opt/anaconda3/bin/python"
    else
        err "venv is required but missing at $VENV_PY. Recreate venv or set ALLOW_BASE_FALLBACK=1."
    fi
fi

for f in ".env" "generate_token.py" "process_guard.py"; do
    [ -f "$ROOT_DIR/$f" ] || err "Required file missing: $f"
done

echo ""
echo "══════════════════════════════════════════"
echo "  Local startup (Kite + services)"
echo "══════════════════════════════════════════"
echo ""
info "Using Python: $PYTHON_BIN"

if [ "$PYTHON_BIN" = "$VENV_PY" ]; then
    info "Runtime mode: venv (preferred)"
else
    warn "Runtime mode: fallback interpreter (not venv)"
fi

if ! "$PYTHON_BIN" -c "import streamlit, kiteconnect, dotenv" >/dev/null 2>&1; then
    err "Missing runtime packages in selected Python. Install dependencies first."
fi

info "Getting Kite login URL..."
LOGIN_URL="$("$PYTHON_BIN" -c "from kite_data import kite_login_url; print(kite_login_url())" 2>/dev/null || true)"
if [ -z "$LOGIN_URL" ]; then
    err "Could not fetch Kite login URL. Check .env and Python runtime."
fi

echo ""
echo -e "${BLUE}Open this URL:${NC}"
echo -e "${BLUE}$LOGIN_URL${NC}"
echo ""
open "$LOGIN_URL" 2>/dev/null || xdg-open "$LOGIN_URL" 2>/dev/null || true
echo "After login, copy request_token from redirect URL."
echo "Example: ...?request_token=XXXXX&status=success"
echo ""
read -r -p "Paste request_token: " REQUEST_TOKEN
[ -n "${REQUEST_TOKEN:-}" ] || err "No token provided."

info "Exchanging request token..."
"$PYTHON_BIN" generate_token.py "$REQUEST_TOKEN" || err "Token exchange failed."
[ -s ".kite_access_token" ] || err ".kite_access_token missing/empty after token exchange."
log "Token saved to .kite_access_token"

info "Starting local watchdog (dashboard + engine + ticker + monitors)..."
echo "Press Ctrl+C to stop services."
echo ""
exec "$PYTHON_BIN" process_guard.py

