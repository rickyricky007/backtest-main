#!/bin/bash
# ============================================================
#  AlgoTrading VPS Setup Script
#  Ubuntu 22.04 LTS — One command full setup
#  Usage: bash setup_vps.sh <your_github_repo_url>
#
#  Example:
#    bash setup_vps.sh https://github.com/yourusername/backtest-main.git
# ============================================================

set -e  # Exit on any error

REPO_URL=${1:-""}
APP_DIR="/opt/algotrading"
SERVICE_USER="algotrading"
PYTHON_VERSION="python3.11"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✅ OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[⚠️  WARN]${NC} $1"; }
err()  { echo -e "${RED}[❌ ERROR]${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[ℹ️  INFO]${NC} $1"; }

echo ""
echo "=============================================="
echo "  AlgoTrading VPS Setup"
echo "=============================================="
echo ""

# ── Validate input ─────────────────────────────────────────────────────────────
if [ -z "$REPO_URL" ]; then
    err "Usage: bash setup_vps.sh <github_repo_url>"
fi

# ── 1. System update ──────────────────────────────────────────────────────────
info "Updating system packages..."
apt-get update -qq && apt-get upgrade -y -qq
log "System updated"

# ── 2. Install dependencies ───────────────────────────────────────────────────
info "Installing system dependencies..."
apt-get install -y -qq \
    python3.11 python3.11-venv python3.11-dev \
    python3-pip git curl wget nginx ufw \
    build-essential libpq-dev \
    supervisor cron
log "Dependencies installed"

# ── 3. Create app user ────────────────────────────────────────────────────────
info "Creating service user: $SERVICE_USER"
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd -r -m -d /opt/algotrading -s /bin/bash $SERVICE_USER
    log "User $SERVICE_USER created"
else
    log "User $SERVICE_USER already exists"
fi

# ── 4. Clone repository ───────────────────────────────────────────────────────
info "Cloning repository..."
if [ -d "$APP_DIR/app" ]; then
    warn "Directory exists — pulling latest code"
    cd "$APP_DIR/app" && git pull
else
    git clone "$REPO_URL" "$APP_DIR/app"
fi
chown -R $SERVICE_USER:$SERVICE_USER $APP_DIR
log "Repository ready at $APP_DIR/app"

# ── 5. Python virtual environment ─────────────────────────────────────────────
info "Setting up Python virtual environment..."
cd "$APP_DIR/app"
sudo -u $SERVICE_USER $PYTHON_VERSION -m venv venv
log "Virtual environment created"

# ── 6. Install Python packages ────────────────────────────────────────────────
info "Installing Python packages (this takes 2-3 minutes)..."
sudo -u $SERVICE_USER bash -c "
    cd $APP_DIR/app
    source venv/bin/activate
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
    pip install psycopg2-binary supabase breeze-connect -q
"
log "Python packages installed"

# ── 7. Create .env file ───────────────────────────────────────────────────────
info "Setting up environment file..."
if [ ! -f "$APP_DIR/app/.env" ]; then
    cp "$APP_DIR/app/.env.example" "$APP_DIR/app/.env" 2>/dev/null || \
    cat > "$APP_DIR/app/.env" << 'ENVFILE'
# ── Kite (Zerodha) ──────────────────────────────────────────────────────────
KITE_API_KEY=
KITE_API_SECRET=

# ── Telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL=
SUPABASE_KEY=
DATABASE_URL=

# ── ICICI Breeze ──────────────────────────────────────────────────────────────
BREEZE_API_KEY=
BREEZE_API_SECRET=

# ── Anthropic ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY=
ENVFILE
    chown $SERVICE_USER:$SERVICE_USER "$APP_DIR/app/.env"
    chmod 600 "$APP_DIR/app/.env"
    warn ".env file created — EDIT IT NOW: nano $APP_DIR/app/.env"
else
    log ".env file already exists"
fi

# ── 8. Create systemd services ────────────────────────────────────────────────
info "Creating systemd services..."

# Streamlit Dashboard service
cat > /etc/systemd/system/algotrading-dashboard.service << SVCFILE
[Unit]
Description=AlgoTrading Streamlit Dashboard
After=network.target
Wants=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_DIR/app
Environment=PATH=$APP_DIR/app/venv/bin
ExecStart=$APP_DIR/app/venv/bin/streamlit run app.py --server.port=8501 --server.address=0.0.0.0 --server.headless=true --server.enableCORS=false
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCFILE

# Token Monitor service
cat > /etc/systemd/system/algotrading-token.service << SVCFILE
[Unit]
Description=AlgoTrading Token Monitor
After=network.target algotrading-dashboard.service

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_DIR/app
Environment=PATH=$APP_DIR/app/venv/bin
ExecStart=$APP_DIR/app/venv/bin/python token_monitor.py
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCFILE

# Scheduler service (daily report, backup, etc.)
cat > /etc/systemd/system/algotrading-scheduler.service << SVCFILE
[Unit]
Description=AlgoTrading Scheduler (Daily Report + Backup)
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_DIR/app
Environment=PATH=$APP_DIR/app/venv/bin
ExecStart=$APP_DIR/app/venv/bin/python scheduler.py
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCFILE

# Process Guard service
cat > /etc/systemd/system/algotrading-guard.service << SVCFILE
[Unit]
Description=AlgoTrading Process Guard (Watchdog)
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_DIR/app
Environment=PATH=$APP_DIR/app/venv/bin
ExecStart=$APP_DIR/app/venv/bin/python process_guard.py
Restart=always
RestartSec=60
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCFILE

log "Systemd services created"

# ── 9. Enable and start services ──────────────────────────────────────────────
info "Enabling services..."
systemctl daemon-reload
systemctl enable algotrading-dashboard
systemctl enable algotrading-token
systemctl enable algotrading-scheduler
systemctl enable algotrading-guard
log "Services enabled (auto-start on reboot)"

# ── 10. Nginx reverse proxy ───────────────────────────────────────────────────
info "Configuring Nginx..."
cat > /etc/nginx/sites-available/algotrading << 'NGINXCONF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://localhost:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 86400;
    }
}
NGINXCONF

ln -sf /etc/nginx/sites-available/algotrading /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx
log "Nginx configured"

# ── 11. Firewall ───────────────────────────────────────────────────────────────
info "Configuring firewall..."
ufw --force enable
ufw allow ssh
ufw allow 80/tcp    # HTTP dashboard
ufw allow 443/tcp   # HTTPS (future)
ufw allow 8501/tcp  # Streamlit direct
log "Firewall configured"

# ── 12. Start services ─────────────────────────────────────────────────────────
info "Starting services..."
systemctl start algotrading-dashboard
sleep 3
systemctl start algotrading-scheduler
systemctl start algotrading-guard

# Don't start token monitor yet — needs .env filled first
warn "Token monitor NOT started — fill .env first"

# ── Done ───────────────────────────────────────────────────────────────────────
VPS_IP=$(curl -s ifconfig.me 2>/dev/null || echo "your-vps-ip")

echo ""
echo "=============================================="
echo -e "${GREEN}  ✅ VPS SETUP COMPLETE!${NC}"
echo "=============================================="
echo ""
echo -e "  Dashboard URL: ${BLUE}http://$VPS_IP${NC}"
echo -e "  Direct port:   ${BLUE}http://$VPS_IP:8501${NC}"
echo ""
echo "  Next steps:"
echo "  1. Fill your secrets: nano $APP_DIR/app/.env"
echo "  2. Start token monitor: systemctl start algotrading-token"
echo "  3. Check status: bash $APP_DIR/app/deploy/status.sh"
echo ""
echo "  Useful commands:"
echo "  View dashboard logs:  journalctl -u algotrading-dashboard -f"
echo "  View scheduler logs:  journalctl -u algotrading-scheduler -f"
echo "  Restart all:          bash $APP_DIR/app/deploy/restart.sh"
echo ""
