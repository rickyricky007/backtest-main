#!/bin/bash
# ── Pull latest code from GitHub and restart ──────────────────────────────────

APP_DIR="/opt/algotrading/app"

echo "Pulling latest code from GitHub..."
cd $APP_DIR
git pull

echo "Installing any new packages..."
source venv/bin/activate
pip install -r requirements.txt -q
pip install psycopg2-binary supabase breeze-connect -q

echo "Installing yfinance (global market data)..."
source venv/bin/activate
pip install yfinance -q

echo "Restarting services..."
bash "$APP_DIR/deploy/restart.sh"
echo "✅ Update complete"
