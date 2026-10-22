"""Resolve data directories from environment."""

import os
from pathlib import Path


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def knowledge_folder_name() -> str:
    """Subfolder inside the Open WebUI knowledge base (e.g. Activities)."""
    return (os.getenv("OPENWEBUI_KB_FOLDER") or "").strip().strip("/")


def knowledge_relative_path(relative_path: str) -> str:
    """Path of a file relative to the knowledge base root (for sync/diff API)."""
    relative_path = relative_path.strip("/")
    folder = knowledge_folder_name()
    if folder:
        return f"{folder}/{relative_path}"
    return relative_path


def knowledge_directory_path(store_parent_relpath: str) -> str:
    """
    Knowledge-base directory path for Open WebUI sync/diff (no filename).

    ``store_parent_relpath`` is relative to the activity store root, e.g. ``2026/10``.
    """
    store_parent_relpath = store_parent_relpath.strip("/")
    if not store_parent_relpath:
        return knowledge_folder_name() or ""
    return knowledge_relative_path(store_parent_relpath)


def strip_kb_folder_prefix(path: str) -> str:
    """Drop leading KB folder segment from a manifest path returned by Open WebUI."""
    folder = knowledge_folder_name()
    if not folder:
        return path.strip("/")
    prefix = f"{folder}/"
    if path.startswith(prefix):
        return path[len(prefix) :]
    return path.strip("/")


def resolve_output_dir() -> str:
    """
    Directory for per-activity Markdown files on disk (YYYY/MM/*.md).

    With Open WebUI configured, defaults to
    OUTPUT_DIR/<OPENWEBUI_KNOWLEDGE_ID>/[<OPENWEBUI_KB_FOLDER>/].
    Set OPENWEBUI_KB_SUBDIR=false to skip the knowledge-id segment only.
    """
    base = (os.getenv("OUTPUT_DIR") or "/data").strip()
    path = Path(base)

    knowledge_id = (os.getenv("OPENWEBUI_KNOWLEDGE_ID") or "").strip()
    if knowledge_id and _truthy(os.getenv("OPENWEBUI_KB_SUBDIR"), default=True):
        path = path / knowledge_id

    folder = knowledge_folder_name()
    if folder:
        path = path / folder

    return str(path)
