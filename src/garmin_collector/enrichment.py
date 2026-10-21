"""Fetch per-activity details from Garmin Connect."""

from __future__ import annotations

import logging
from typing import Any, Callable

from garminconnect import Garmin

logger = logging.getLogger(__name__)


def _safe_fetch(label: str, fn: Callable[[], Any]) -> Any | None:
    try:
        return fn()
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", label, exc)
        return None


def fetch_activity_enrichment(client: Garmin, activity_id: str | int) -> dict[str, Any]:
    """Load optional activity payloads; missing data is returned as None."""
    aid = str(activity_id)
    return {
        "weather": _safe_fetch("weather", lambda: client.get_activity_weather(aid)),
        "gear": _safe_fetch("gear", lambda: client.get_activity_gear(aid)),
        "hr_zones": _safe_fetch("hr_zones", lambda: client.get_activity_hr_in_timezones(aid)),
        "power_zones": _safe_fetch("power_zones", lambda: client.get_activity_power_in_timezones(aid)),
        "splits": _safe_fetch("splits", lambda: client.get_activity_splits(aid)),
    }
