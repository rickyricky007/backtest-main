"""
config.py — Centralised environment variable loader
====================================================
Handles all .env key names (both old and new naming conventions).

Import this everywhere instead of reading os.getenv() directly:

    from config import cfg
    token   = cfg.telegram_bot_token
    chat_id = cfg.telegram_chat_id
    api_key = cfg.kite_api_key
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

_BASE = Path(__file__).parent
load_dotenv(_BASE / ".env", override=False)

def _get(*keys: str, default: str = "") -> str:
    """Try each key name in order, return first match."""
    for k in keys:
        v = os.getenv(k, "").strip()
        if v:
            return v
    return default


class _Config:
    # ── Kite ────────────────────────────────────────────────────────────────
    @property
    def kite_api_key(self) -> str:
        return _get("KITE_API_KEY", "API_KEY")

    @property
    def kite_api_secret(self) -> str:
        return _get("KITE_API_SECRET", "API_SECRET")

    # ── Telegram ─────────────────────────────────────────────────────────────
    @property
    def telegram_bot_token(self) -> str:
        return _get("TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN")

    @property
    def telegram_chat_id(self) -> str:
        return _get("TELEGRAM_CHAT_ID")

    # ── Anthropic ─────────────────────────────────────────────────────────────
    @property
    def anthropic_api_key(self) -> str:
        return _get("ANTHROPIC_API_KEY")

    # ── Kite login URL ─────────────────────────────────────────────────────────
    @property
    def kite_login_url(self) -> str:
        key = self.kite_api_key
        if key:
            return f"https://kite.zerodha.com/connect/login?api_key={key}&v=3"
        return "https://kite.zerodha.com"

    def summary(self) -> dict:
        return {
            "kite_api_key":     self.kite_api_key[:6] + "..." if self.kite_api_key else "MISSING",
            "telegram_token":   "✅ set" if self.telegram_bot_token else "❌ missing",
            "telegram_chat_id": "✅ set" if self.telegram_chat_id else "❌ missing",
            "anthropic_key":    "✅ set" if self.anthropic_api_key else "❌ missing",
        }


cfg = _Config()


if __name__ == "__main__":
    import json
    print(json.dumps(cfg.summary(), indent=2))
