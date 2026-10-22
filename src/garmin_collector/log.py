"""Stdout logging with UTC timestamps (Docker/cron friendly)."""

from __future__ import annotations

import logging
import sys
import time


class _UTCFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created))


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_UTCFormatter("%(asctime)s %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
