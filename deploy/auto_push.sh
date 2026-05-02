#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
#  Auto Push to GitHub — runs via cron every hour
#  Only pushes if there are actual changes (won't push if nothing changed)
#
#  Setup (run once on VPS):
#    sudo bash deploy/auto_push.sh --install
#
#  Manual run:
#    bash deploy/auto_push.sh
# ══════════════════════════════════════════════════════════════════════════════

APP_DIR="/opt/algotrading/app"
LOG_FILE="/var/log/algotrading/auto_push.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# ── Install mode: sets up cron job ────────────────────────────────────────────
if [ "$1" == "--install" ]; then
    echo "Setting up hourly auto-push cron job..."
    
    # Create log directory
    mkdir -p /var/log/algotrading
    
    # Add cron job for algotrading user — runs every hour
    CRON_LINE="0 * * * * bash $APP_DIR/deploy/auto_push.sh >> $LOG_FILE 2>&1"
    (crontab -l 2>/dev/null | grep -v "auto_push"; echo "$CRON_LINE") | crontab -
    
    echo "✅ Cron job installed — auto-push runs every hour"
    echo "   Log: $LOG_FILE"
    crontab -l | grep auto_push
    exit 0
fi

# ── Main: check for changes and push ─────────────────────────────────────────
cd "$APP_DIR" || exit 1

# Fix safe directory
git config --global --add safe.directory "$APP_DIR" 2>/dev/null

# Check if there are any changes (unstaged OR staged OR untracked)
if [ -z "$(git status --porcelain)" ]; then
    echo "[$TIMESTAMP] No changes — nothing to push"
    exit 0
fi

# Stage all changes (except .gitignore'd files)
git add -A

# Commit with timestamp
git commit -m "auto: $(date '+%Y-%m-%d %H:%M') — system sync"

# Push to GitHub
if git push origin main 2>&1; then
    echo "[$TIMESTAMP] ✅ Pushed to GitHub successfully"
else
    echo "[$TIMESTAMP] ❌ Push failed — check git remote and credentials"
    exit 1
fi