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


def knowledge_relative_path(filename: str) -> str:
    """Path of a file relative to the knowledge base root (for sync/diff API)."""
    folder = knowledge_folder_name()
    if folder:
        return f"{folder}/{filename}"
    return filename


def resolve_output_dir() -> str:
    """
    Directory for monthly Markdown files on disk.

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
