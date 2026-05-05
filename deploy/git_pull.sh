#!/usr/bin/env bash
# ── Git pull only (as algotrading) — use for quick daily sync without pip/restart ─
#
# Usage:
#   sudo bash /opt/algotrading/app/deploy/git_pull.sh
#   # or as algotrading:
#   bash /opt/algotrading/app/deploy/git_pull.sh
#
# For pull + deps + service restart, use: deploy/update.sh

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/algotrading/app}"
SERVICE_USER="${SERVICE_USER:-algotrading}"

if [ ! -d "$APP_DIR/.git" ]; then
  echo "ERROR: $APP_DIR is not a git repository."
  exit 1
fi

_sync_pull() {
  cd "$APP_DIR"
  git config pull.rebase false
  git pull --no-rebase
}

if [ "$(id -un)" = "$SERVICE_USER" ]; then
  _sync_pull
else
  sudo -u "$SERVICE_USER" -H bash -c "cd '$APP_DIR' && git config pull.rebase false && git pull --no-rebase"
fi

echo "✅ git pull complete (restart services separately if needed)"
