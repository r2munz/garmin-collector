"""One Markdown file per activity under YYYY/MM/."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from garmin_collector.format_activity import merge_session_notes

logger = logging.getLogger(__name__)

LEGACY_MONTHLY_FILE_PATTERN = re.compile(r"^activities_(\d{4})-(\d{2})\.md$")
ACTIVITY_FILE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*_\d+\.md$", re.IGNORECASE)


def activity_month_key(start_time_local: str | None) -> str | None:
    from datetime import datetime

    if not start_time_local:
        return None
    try:
        dt = datetime.strptime(start_time_local[:10], "%Y-%m-%d")
    except ValueError:
        return None
    return f"{dt.year:04d}-{dt.month:02d}"


def sanitize_activity_type(type_key: str | None) -> str:
    if not type_key:
        return "activity"
    slug = re.sub(r"[^a-z0-9_]+", "_", type_key.lower()).strip("_")
    return slug or "activity"


def activity_filename(activity_type: str | None, activity_id: str) -> str:
    return f"{sanitize_activity_type(activity_type)}_{activity_id}.md"


def activity_relpath(month_key: str, activity_type: str | None, activity_id: str) -> str:
    year, month = month_key.split("-")
    return f"{year}/{month}/{activity_filename(activity_type, activity_id)}"


def activity_file_path(output_dir: str, month_key: str, activity_type: str | None, activity_id: str) -> str:
    return os.path.join(output_dir, activity_relpath(month_key, activity_type, activity_id))


def has_existing_activity_store(output_dir: str) -> bool:
    """True if per-activity files exist, or legacy monthly aggregates are present."""
    if not os.path.isdir(output_dir):
        return False
    for name in os.listdir(output_dir):
        if LEGACY_MONTHLY_FILE_PATTERN.match(name):
            return True
    for root, _, files in os.walk(output_dir):
        for name in files:
            if ACTIVITY_FILE_PATTERN.match(name):
                return True
    return False


def _read_file(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def find_activity_paths(output_dir: str, activity_id: str) -> list[str]:
    """All stored paths for this activity id (normally zero or one)."""
    found: list[str] = []
    suffix = f"_{activity_id}.md"
    for root, _, files in os.walk(output_dir):
        for name in files:
            if name.endswith(suffix) and ACTIVITY_FILE_PATTERN.match(name):
                found.append(os.path.join(root, name))
    return found


def remove_stale_activity_files(output_dir: str, activity_id: str, keep_path: str) -> None:
    keep_path = os.path.normpath(keep_path)
    for path in find_activity_paths(output_dir, activity_id):
        if os.path.normpath(path) == keep_path:
            continue
        os.remove(path)
        logger.info("Removed stale activity file %s", path)


def upsert_activity_file(
    output_dir: str,
    month_key: str,
    activity_id: str,
    activity_type: str | None,
    body: str,
) -> tuple[str, str]:
    """
    Write one activity Markdown file.
    Returns (action, relpath) where action is 'created' or 'updated'.
    """
    path = activity_file_path(output_dir, month_key, activity_type, activity_id)
    relpath = activity_relpath(month_key, activity_type, activity_id)
    remove_stale_activity_files(output_dir, activity_id, path)

    previous: str | None = None
    if os.path.isfile(path):
        previous = _read_file(path)

    content = merge_session_notes(previous, body)
    is_update = previous is not None
    _write_file(path, content)

    action = "updated" if is_update else "created"
    logger.info("%s activity %s at %s", action.capitalize(), activity_id, relpath)
    return action, relpath
