#!/usr/bin/env bash
# ── Pull latest code, install deps, restart (VPS-safe permissions) ───────────
#
# Problem this fixes: repo under /opt/algotrading/app is owned by `algotrading`.
# Running `git pull` as `ubuntu` causes "cannot open .git/FETCH_HEAD: Permission denied".
#
# Usage (pick ONE):
#   sudo bash /opt/algotrading/app/deploy/update.sh          # from ubuntu — recommended
#   bash /opt/algotrading/app/deploy/update.sh                 # as user algotrading (no sudo)
#
# See: deploy/GIT_AND_PERMISSIONS.md

set -euo pipefail

APP_DIR="/opt/algotrading/app"
SERVICE_USER="algotrading"

if [ ! -d "$APP_DIR/.git" ]; then
  echo "ERROR: $APP_DIR is not a git repo."
  exit 1
fi

if ! id "$SERVICE_USER" &>/dev/null; then
  echo "ERROR: system user '$SERVICE_USER' does not exist. Run deploy/setup_vps.sh first."
  exit 1
fi

echo "Pulling latest code and updating venv as **$SERVICE_USER**..."

# Git 2.27+: avoid "Need to specify how to reconcile divergent branches"
# Local repo setting (once): merge on pull; then pull always has a strategy.
_git_pull_merge() {
  cd "$APP_DIR"
  git config pull.rebase false
  git pull --no-rebase
}

if [ "$(id -un)" = "$SERVICE_USER" ]; then
  _git_pull_merge
  # shellcheck source=/dev/null
  source venv/bin/activate
  pip install -r requirements.txt -q
  pip install psycopg2-binary supabase breeze-connect -q
  pip install yfinance -q
else
  sudo -u "$SERVICE_USER" -H bash <<EOS
set -euo pipefail
cd "$APP_DIR"
git config pull.rebase false
git pull --no-rebase
source venv/bin/activate
pip install -r requirements.txt -q
pip install psycopg2-binary supabase breeze-connect -q
pip install yfinance -q
EOS
fi

echo "Restarting services..."
if [ "${EUID:-$(id -u)}" -eq 0 ]; then
  bash "$APP_DIR/deploy/restart.sh"
else
  sudo bash "$APP_DIR/deploy/restart.sh"
fi

echo "✅ Update complete"
