#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
#  AlgoTrading — VPS Fix Script
#  Run this ON THE VPS after SSH'ing in
#
#  Fixes:
#    1. ticker_data.json permissions (live ticker showing as off)
#    2. Adds algotrading-ticker systemd service (if missing)
#    3. Adds algotrading-breeze systemd service (Breeze session monitor)
#    4. Fixes directory permissions
#    5. Installs missing packages (breeze-connect, yfinance)
#    6. Starts all services
#
#  Usage (on VPS after ssh vps):
#    sudo bash /opt/algotrading/app/deploy/fix_vps.sh
# ══════════════════════════════════════════════════════════════════════════════

APP_DIR="/opt/algotrading/app"
SERVICE_USER="algotrading"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✅ OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[⚠️]${NC} $1"; }

echo ""
echo "══════════════════════════════════════════"
echo "  🔧 AlgoTrading VPS Fix"
echo "══════════════════════════════════════════"
echo ""

# ── 1. Fix directory permissions ─────────────────────────────────────────────
echo "[1/6] Fixing directory permissions..."
chmod 755 $APP_DIR
chown -R $SERVICE_USER:$SERVICE_USER $APP_DIR
# Make ticker_data.json world-readable if it exists
[ -f "$APP_DIR/ticker_data.json" ] && chmod 644 $APP_DIR/ticker_data.json
log "Permissions fixed"

# ── 2. Install missing packages ───────────────────────────────────────────────
echo "[2/6] Installing missing packages..."
sudo -u $SERVICE_USER bash -c "
    source $APP_DIR/venv/bin/activate
    pip install breeze-connect yfinance -q
"
log "Packages installed"

# ── 3. Add ticker systemd service (if missing) ───────────────────────────────
echo "[3/6] Checking ticker service..."
if [ ! -f /etc/systemd/system/algotrading-ticker.service ]; then
    cat > /etc/systemd/system/algotrading-ticker.service << 'SVCFILE'
[Unit]
Description=AlgoTrading Live Ticker (Kite WebSocket)
After=network.target algotrading-dashboard.service

[Service]
Type=simple
User=algotrading
WorkingDirectory=/opt/algotrading/app
Environment=PATH=/opt/algotrading/app/venv/bin
ExecStart=/opt/algotrading/app/venv/bin/python ticker_service.py
Restart=always
RestartSec=30
UMask=0022
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCFILE
    log "Ticker service created"
else
    # Update existing service to add UMask (fixes permissions)
    sed -i '/RestartSec=30/a UMask=0022' /etc/systemd/system/algotrading-ticker.service 2>/dev/null || true
    log "Ticker service already exists (updated UMask)"
fi

# ── 4. Add Breeze session monitor service ─────────────────────────────────────
echo "[4/6] Adding Breeze session monitor..."
cat > /etc/systemd/system/algotrading-breeze.service << 'SVCFILE'
[Unit]
Description=AlgoTrading Breeze Session Monitor
After=network.target

[Service]
Type=simple
User=algotrading
WorkingDirectory=/opt/algotrading/app
Environment=PATH=/opt/algotrading/app/venv/bin
ExecStart=/opt/algotrading/app/venv/bin/python breeze_monitor.py
Restart=always
RestartSec=60
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCFILE
log "Breeze service created"

# ── 5. Reload and enable services ─────────────────────────────────────────────
echo "[5/6] Enabling all services..."
systemctl daemon-reload
systemctl enable algotrading-ticker
systemctl enable algotrading-breeze
log "Services enabled"

# ── 6. Start all services ─────────────────────────────────────────────────────
echo "[6/6] Starting all services..."
systemctl restart algotrading-dashboard
systemctl restart algotrading-ticker
systemctl restart algotrading-scheduler
systemctl restart algotrading-guard
systemctl restart algotrading-token
# Only start breeze if session token exists
if [ -f "$APP_DIR/.breeze_session" ]; then
    systemctl restart algotrading-breeze
    log "Breeze service started"
else
    warn "Breeze session not found — run: python breeze_data.py --token YOUR_TOKEN"
fi
log "All services started"

echo ""
echo "══════════════════════════════════════════"
echo -e "${GREEN}  ✅ VPS Fix Complete!${NC}"
echo "══════════════════════════════════════════"
echo ""

# Show status
bash $APP_DIR/deploy/status.sh
