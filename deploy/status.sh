#!/bin/bash
# ── Service Status Checker ────────────────────────────────────────────────────

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo "=========================================="
echo "  AlgoTrading Service Status"
echo "=========================================="
echo ""

check_service() {
    local name=$1
    local service=$2
    if systemctl is-active --quiet $service; then
        echo -e "  ${GREEN}✅ RUNNING${NC}  $name"
    else
        echo -e "  ${RED}❌ STOPPED${NC}  $name"
    fi
}

check_service "Streamlit Dashboard" "algotrading-dashboard"
check_service "Token Monitor"       "algotrading-token"
check_service "Live Ticker (Kite)"  "algotrading-ticker"
check_service "Breeze Monitor"      "algotrading-breeze"
check_service "Scheduler"           "algotrading-scheduler"
check_service "Process Guard"       "algotrading-guard"
check_service "Nginx"               "nginx"

echo ""
VPS_IP=$(curl -s ifconfig.me 2>/dev/null || echo "unknown")
echo "  VPS IP:        $VPS_IP"
echo "  Dashboard URL: http://$VPS_IP"
echo ""

# Check .env populated
APP_DIR="/opt/algotrading/app"
if grep -q "^KITE_API_KEY=$" "$APP_DIR/.env" 2>/dev/null; then
    echo -e "  ${YELLOW}⚠️  .env not filled — edit: nano $APP_DIR/.env${NC}"
else
    echo -e "  ${GREEN}✅ .env configured${NC}"
fi
echo ""
