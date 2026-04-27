#!/bin/bash
# ── Restart all AlgoTrading services ─────────────────────────────────────────

echo "Restarting all services..."
systemctl restart algotrading-dashboard
systemctl restart algotrading-token
systemctl restart algotrading-scheduler
systemctl restart algotrading-guard
systemctl restart nginx
echo "✅ All services restarted"
bash "$(dirname "$0")/status.sh"
