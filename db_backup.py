"""
DB Backup — Local (7 days) + Supabase Storage (permanent cloud copy)
=====================================================================
Runs automatically at 3:30pm via daily_report.py.
Local:  backups/dashboard_YYYYMMDD_HHMM.sqlite  (keeps last 7)
Cloud:  Supabase Storage bucket "db-backups"     (permanent)

Usage:
    python db_backup.py          # run manually
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from config import cfg
from logger import get_logger
from telegram import _send

log = get_logger("db_backup")

BASE_DIR   = Path(__file__).parent
DB_FILE    = BASE_DIR / "dashboard.sqlite"
BACKUP_DIR = BASE_DIR / "backups"
KEEP_DAYS  = 7
BUCKET     = "db-backups"


# ── Supabase Storage client ───────────────────────────────────────────────────

def _storage_client():
    """Return Supabase storage client, or None if not configured."""
    try:
        from supabase import create_client
        url = cfg.supabase_url
        key = cfg.supabase_key
        if not url or not key:
            log.warning("Supabase URL or key not set — cloud backup skipped")
            return None
        return create_client(url, key).storage
    except Exception:
        log.error("Could not create Supabase client", exc_info=True)
        return None


def _ensure_bucket(storage) -> bool:
    """Create the backup bucket if it doesn't exist."""
    try:
        buckets = [b.name for b in storage.list_buckets()]
        if BUCKET not in buckets:
            storage.create_bucket(BUCKET, options={"public": False})
            log.info(f"Created Supabase Storage bucket: {BUCKET}")
        return True
    except Exception:
        log.error("Could not ensure Supabase bucket exists", exc_info=True)
        return False


# ── Cloud upload ──────────────────────────────────────────────────────────────

def _upload_to_supabase(backup_file: Path) -> bool:
    """Upload a backup file to Supabase Storage."""
    storage = _storage_client()
    if not storage:
        return False

    try:
        if not _ensure_bucket(storage):
            return False

        with open(backup_file, "rb") as f:
            storage.from_(BUCKET).upload(
                path         = backup_file.name,
                file         = f,
                file_options = {"content-type": "application/octet-stream", "upsert": "true"},
            )

        log.info(f"☁️  Uploaded to Supabase Storage: {backup_file.name}")
        return True

    except Exception:
        log.error("Supabase Storage upload failed", exc_info=True)
        return False


# ── Local backup ──────────────────────────────────────────────────────────────

def run_backup() -> bool:
    """
    1. Copy dashboard.sqlite → backups/dashboard_YYYYMMDD_HHMM.sqlite
    2. Upload to Supabase Storage bucket 'db-backups'
    3. Keep last 7 local backups
    4. Send Telegram summary
    """
    try:
        if not DB_FILE.exists():
            log.warning("dashboard.sqlite not found — nothing to backup")
            return False

        BACKUP_DIR.mkdir(exist_ok=True)

        ts          = datetime.now().strftime("%Y%m%d_%H%M")
        backup_file = BACKUP_DIR / f"dashboard_{ts}.sqlite"

        # ── Local copy ────────────────────────────────────────────────────────
        shutil.copy2(DB_FILE, backup_file)
        size_kb = backup_file.stat().st_size // 1024
        log.info(f"✅ Local backup: {backup_file.name} ({size_kb} KB)")

        # ── Cloud upload ──────────────────────────────────────────────────────
        cloud_ok = _upload_to_supabase(backup_file)

        # ── Clean old local backups ───────────────────────────────────────────
        _cleanup()

        # ── Telegram ─────────────────────────────────────────────────────────
        cloud_status = "☁️ Supabase ✅" if cloud_ok else "☁️ Supabase ❌ (check logs)"
        _send(
            f"💾 <b>DB Backup Complete</b>\n"
            f"📁 File  : <code>{backup_file.name}</code>\n"
            f"📦 Size  : {size_kb} KB\n"
            f"🗂 Local : last {KEEP_DAYS} backups kept\n"
            f"{cloud_status}\n"
            f"🕐 {datetime.now().strftime('%d %b %Y %H:%M IST')}"
        )
        return True

    except Exception:
        log.error("DB backup failed", exc_info=True)
        _send(
            f"❌ <b>DB Backup FAILED</b>\n"
            f"🕐 {datetime.now().strftime('%d %b %Y %H:%M IST')}\n"
            f"⚠️ Check logs immediately."
        )
        return False


def _cleanup() -> None:
    """Remove local backups older than KEEP_DAYS."""
    try:
        backups = sorted(BACKUP_DIR.glob("dashboard_*.sqlite"))
        if len(backups) > KEEP_DAYS:
            for old in backups[:-KEEP_DAYS]:
                old.unlink()
                log.info(f"🗑 Deleted old local backup: {old.name}")
    except Exception:
        log.error("Backup cleanup error", exc_info=True)


# ── Restore ───────────────────────────────────────────────────────────────────

def list_backups() -> list[dict]:
    """Return list of local backups with metadata."""
    try:
        backups = sorted(BACKUP_DIR.glob("dashboard_*.sqlite"), reverse=True)
        return [
            {
                "file":    b.name,
                "size_kb": b.stat().st_size // 1024,
                "date":    datetime.fromtimestamp(b.stat().st_mtime).strftime("%d %b %Y %H:%M"),
            }
            for b in backups
        ]
    except Exception:
        log.error("list_backups error", exc_info=True)
        return []


def restore_backup(filename: str) -> bool:
    """Restore a local backup over dashboard.sqlite (saves safety copy first)."""
    try:
        src = BACKUP_DIR / filename
        if not src.exists():
            log.error(f"Backup not found: {filename}")
            return False

        # Safety copy before overwriting
        safety = BASE_DIR / f"dashboard_pre_restore_{datetime.now().strftime('%Y%m%d_%H%M')}.sqlite"
        if DB_FILE.exists():
            shutil.copy2(DB_FILE, safety)
            log.info(f"Safety copy saved: {safety.name}")

        shutil.copy2(src, DB_FILE)
        log.info(f"✅ Restored from: {filename}")
        return True

    except Exception:
        log.error("Restore failed", exc_info=True)
        return False


if __name__ == "__main__":
    ok = run_backup()
    print("✅ Backup complete" if ok else "❌ Backup failed — check logs")
