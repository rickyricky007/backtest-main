#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
#  AlgoTrading — Daily Morning Startup Script
#  Run this on your MAC every morning before 9:15am
#
#  What it does:
#    1. Generates fresh Kite access token
#    2. Copies Kite token to VPS
#    3. Restarts VPS services (ticker, dashboard)
#    4. Reminds you to refresh Breeze token on VPS
#
#  Usage (from "ricky 1" folder):
#    bash deploy/morning_startup.sh
# ══════════════════════════════════════════════════════════════════════════════

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

VPS_IP="65.2.22.171"
VPS_KEY="$HOME/Downloads/algotrading-key.pem"
VPS_USER="ubuntu"
APP_DIR="/opt/algotrading/app"

log()  { echo -e "${GREEN}[✅ OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[⚠️  WARN]${NC} $1"; }
err()  { echo -e "${RED}[❌ ERROR]${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[ℹ️  INFO]${NC} $1"; }

echo ""
echo "══════════════════════════════════════════"
echo "  🌅 AlgoTrading Morning Startup"
echo "══════════════════════════════════════════"
echo ""

# ── Step 1: Get Kite login URL ─────────────────────────────────────────────────
info "Getting Kite login URL..."
LOGIN_URL=$(python -c "from kite_data import kite_login_url; print(kite_login_url())" 2>/dev/null)
if [ -z "$LOGIN_URL" ]; then
    err "Could not get Kite login URL. Make sure you're in 'ricky 1' folder with venv active."
fi

echo ""
echo -e "  ${BLUE}Open this URL in browser:${NC}"
echo -e "  ${BLUE}$LOGIN_URL${NC}"
echo ""

# Auto-open in browser
open "$LOGIN_URL" 2>/dev/null || xdg-open "$LOGIN_URL" 2>/dev/null || true

echo "  After login, copy the request_token from the redirect URL"
echo "  URL looks like: 127.0.0.1/?request_token=XXXXX&status=success"
echo ""
read -p "  Paste request_token here: " REQUEST_TOKEN

if [ -z "$REQUEST_TOKEN" ]; then
    err "No token provided."
fi

# ── Step 2: Generate access token ─────────────────────────────────────────────
info "Generating Kite access token..."
python generate_token.py "$REQUEST_TOKEN"
if [ ! -f ".kite_access_token" ]; then
    err "Token generation failed."
fi
log "Kite token generated"

# ── Step 3: Copy token to VPS ─────────────────────────────────────────────────
info "Copying token to VPS..."
scp -i "$VPS_KEY" -o StrictHostKeyChecking=no \
    .kite_access_token ${VPS_USER}@${VPS_IP}:/tmp/.kite_access_token

ssh -i "$VPS_KEY" -o StrictHostKeyChecking=no ${VPS_USER}@${VPS_IP} \
    "sudo cp /tmp/.kite_access_token ${APP_DIR}/.kite_access_token && \
     sudo chown algotrading:algotrading ${APP_DIR}/.kite_access_token && \
     sudo chmod 600 ${APP_DIR}/.kite_access_token"
log "Kite token copied to VPS"

# ── Step 4: Restart VPS services ──────────────────────────────────────────────
info "Restarting VPS services..."
ssh -i "$VPS_KEY" -o StrictHostKeyChecking=no ${VPS_USER}@${VPS_IP} \
    "sudo systemctl restart algotrading-ticker algotrading-dashboard algotrading-token"
log "VPS services restarted"

# ── Step 5: Breeze token reminder ─────────────────────────────────────────────
echo ""
warn "BREEZE TOKEN: Generate fresh token on VPS now:"
echo "  ssh vps"
echo "  cd /opt/algotrading/app"
echo "  source venv/bin/activate"
echo "  python breeze_data.py --login"
echo "  # Open the URL, login, copy apisession= value"
echo "  python breeze_data.py --token YOUR_SESSION_TOKEN"
echo ""

# ── Done ───────────────────────────────────────────────────────────────────────
echo "══════════════════════════════════════════"
echo -e "${GREEN}  ✅ Morning startup complete!${NC}"
echo "══════════════════════════════════════════"
echo ""
echo -e "  Dashboard: ${BLUE}http://${VPS_IP}${NC}"
echo ""
