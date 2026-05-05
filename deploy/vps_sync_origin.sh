#!/usr/bin/env bash
# ── Force VPS repo = GitHub (DESTRUCTIVE) ─────────────────────────────────────
#
# Drops any **local commits or uncommitted edits** on the server and resets to
# origin/<branch>. Use when `git pull` keeps failing or the dashboard shows old
# code after deploy — typical for a machine that should never diverge from GitHub.
#
# Usage:
#   sudo bash /opt/algotrading/app/deploy/vps_sync_origin.sh          # default branch: main
#   sudo bash /opt/algotrading/app/deploy/vps_sync_origin.sh master   # if your default is master
#
# Then install + restart:
#   sudo bash /opt/algotrading/app/deploy/update.sh
#
# Or sync only (no pip): run this script, then: sudo bash deploy/restart.sh

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/algotrading/app}"
SERVICE_USER="${SERVICE_USER:-algotrading}"
BRANCH="${1:-main}"

if [ ! -d "$APP_DIR/.git" ]; then
  echo "ERROR: $APP_DIR is not a git repo."
  exit 1
fi

echo "⚠️  This will DISCARD local VPS changes and reset to origin/$BRANCH"
echo "    Directory: $APP_DIR"
if [ "${SKIP_CONFIRM:-}" != "1" ]; then
  read -r -p "Type YES to continue: " ok
  if [ "$ok" != "YES" ]; then
    echo "Aborted."
    exit 1
  fi
fi

sudo -u "$SERVICE_USER" -H bash <<EOS
set -euo pipefail
cd "$APP_DIR"
git fetch origin
git checkout "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH" "origin/$BRANCH"
git reset --hard "origin/$BRANCH"
EOS

echo "✅ Repo now matches origin/$BRANCH. Run: sudo bash $APP_DIR/deploy/update.sh"
