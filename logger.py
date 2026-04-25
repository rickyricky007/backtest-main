"""
Central Logger — Algo Trading System
=====================================
Use this in every file instead of print() or bare try/except.

Usage:
    from logger import get_logger
    log = get_logger(__name__)

    log.info("Order placed")
    log.warning("Ticker stale")
    log.error("Kite API failed", exc_info=True)   # includes traceback
    log.critical("Risk limit breached!")
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

_FMT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
_DATE = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str) -> logging.Logger:
    """
    Returns a logger that:
    - Prints to terminal (INFO and above)
    - Writes to logs/<name>.log with rotation (10 MB, 5 backups)
    - Writes ALL errors to logs/errors.log (WARNING and above)
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.DEBUG)

    # ── Terminal handler ──────────────────────────────────────────────────────
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(_FMT, _DATE))
    logger.addHandler(console)

    # ── Per-module rotating file handler ─────────────────────────────────────
    safe_name = name.replace(".", "_").replace("/", "_")
    file_handler = RotatingFileHandler(
        LOG_DIR / f"{safe_name}.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FMT, _DATE))
    logger.addHandler(file_handler)

    # ── Central errors.log (catches WARNING+ from all modules) ───────────────
    error_handler = RotatingFileHandler(
        LOG_DIR / "errors.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(logging.Formatter(_FMT, _DATE))
    logger.addHandler(error_handler)

    return logger
