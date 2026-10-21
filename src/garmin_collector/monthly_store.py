"""Read/write monthly Markdown activity files with upsert by activity ID."""

from __future__ import annotations

import os
import re
from calendar import month_name

from garmin_collector.format_activity import merge_session_notes


def monthly_file_header(month_key: str) -> str:
    year_str, month_str = month_key.split("-")
    label = f"{month_name[int(month_str)]} {year_str}"
    return f"# Activities — {label}\n\n"

MONTHLY_FILE_PATTERN = re.compile(r"^activities_(\d{4})-(\d{2})\.md$")
ACTIVITY_ID_MARKER = re.compile(r"<!--\s*garmin-activity-id:\s*(\d+)\s*-->")
SECTION_SPLIT = re.compile(r"(?=^## )", re.MULTILINE)


def activity_month_key(start_time_local: str | None) -> str | None:
    from datetime import datetime

    if not start_time_local:
        return None
    try:
        dt = datetime.strptime(start_time_local[:10], "%Y-%m-%d")
    except ValueError:
        return None
    return f"{dt.year:04d}-{dt.month:02d}"


def monthly_file_path(output_dir: str, month_key: str) -> str:
    return os.path.join(output_dir, f"activities_{month_key}.md")


def has_existing_monthly_store(output_dir: str) -> bool:
    if not os.path.isdir(output_dir):
        return False
    return any(MONTHLY_FILE_PATTERN.match(name) for name in os.listdir(output_dir))


def _parse_monthly_content(content: str) -> tuple[str, list[tuple[str, str]]]:
    """Return file preamble (month title) and ordered (activity_id, section) pairs."""
    content = content.strip()
    if not content:
        return "", []

    parts = SECTION_SPLIT.split(content)
    preamble = parts[0]
    if not preamble.endswith("\n"):
        preamble += "\n"

    sections: list[tuple[str, str]] = []
    for part in parts[1:]:
        part = part.strip()
        if not part:
            continue
        match = ACTIVITY_ID_MARKER.search(part)
        if not match:
            continue
        sections.append((match.group(1), part + "\n"))

    return preamble, sections


def _render_monthly_file(preamble: str, sections: list[tuple[str, str]]) -> str:
    if not sections:
        return preamble if preamble.endswith("\n") else preamble + "\n"
    body = "\n---\n\n".join(section.rstrip() for _, section in sections)
    return preamble.rstrip() + "\n\n" + body + "\n"


def _read_file(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write_file(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _extract_section_by_id(content: str, activity_id: str) -> str | None:
    _, sections = _parse_monthly_content(content)
    for aid, section in sections:
        if aid == activity_id:
            return section
    return None


def remove_activity_from_other_months(
    output_dir: str, activity_id: str, keep_path: str
) -> None:
    """Drop activity from any monthly file except the target month (e.g. after date change)."""
    if not os.path.isdir(output_dir):
        return
    keep_path = os.path.normpath(keep_path)
    for name in os.listdir(output_dir):
        if not MONTHLY_FILE_PATTERN.match(name):
            continue
        path = os.path.normpath(os.path.join(output_dir, name))
        if path == keep_path:
            continue
        content = _read_file(path)
        if activity_id not in ACTIVITY_ID_MARKER.findall(content):
            continue
        preamble, sections = _parse_monthly_content(content)
        sections = [(aid, sec) for aid, sec in sections if aid != activity_id]
        _write_file(path, _render_monthly_file(preamble, sections))
        print(f"Removed activity {activity_id} from {name} (moved month)")


def upsert_activity_section(
    output_dir: str,
    month_key: str,
    activity_id: str,
    section: str,
) -> str:
    """
    Insert or replace activity section in the monthly file.
    Returns 'created', 'updated', or 'unchanged' (unchanged not used today).
    """
    path = monthly_file_path(output_dir, month_key)
    remove_activity_from_other_months(output_dir, activity_id, path)

    previous_section: str | None = None
    if os.path.isfile(path):
        previous_section = _extract_section_by_id(_read_file(path), activity_id)

    section = merge_session_notes(previous_section, section)
    is_update = previous_section is not None

    if os.path.isfile(path):
        preamble, sections = _parse_monthly_content(_read_file(path))
        if not preamble.strip():
            preamble = monthly_file_header(month_key)
        replaced = False
        new_sections: list[tuple[str, str]] = []
        for aid, existing in sections:
            if aid == activity_id:
                new_sections.append((aid, section))
                replaced = True
            else:
                new_sections.append((aid, existing))
        if not replaced:
            new_sections.append((activity_id, section))
        _write_file(path, _render_monthly_file(preamble, new_sections))
    else:
        preamble = monthly_file_header(month_key)
        _write_file(path, _render_monthly_file(preamble, [(activity_id, section)]))
        is_update = False

    action = "updated" if is_update else "created"
    print(f"{action.capitalize()} activity {activity_id} in {path}")
    return action
