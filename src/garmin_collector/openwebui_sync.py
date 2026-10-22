"""Push monthly Markdown exports to an Open WebUI knowledge base (vector/RAG)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from garmin_collector.activity_store import (
    ACTIVITY_FILE_PATTERN,
    LEGACY_MONTHLY_FILE_PATTERN,
    LEGACY_PER_ACTIVITY_FILE_PATTERN,
)
from garmin_collector.paths import (
    knowledge_directory_path,
    knowledge_folder_name,
    strip_kb_folder_prefix,
)

logger = logging.getLogger(__name__)


def _http_error_detail(exc: requests.HTTPError) -> str:
    if exc.response is None:
        return str(exc)
    try:
        body = exc.response.text.strip()
    except Exception:
        body = ""
    if body:
        return f"{exc.response.status_code} {exc.response.reason}: {body[:500]}"
    return f"{exc.response.status_code} {exc.response.reason}"

DEFAULT_POLL_INTERVAL_SEC = 2.0
DEFAULT_PROCESS_TIMEOUT_SEC = 300.0


@dataclass(frozen=True)
class OpenWebUIConfig:
    base_url: str
    api_key: str
    knowledge_id: str
    process_timeout_sec: float = DEFAULT_PROCESS_TIMEOUT_SEC

    @classmethod
    def from_env(cls) -> OpenWebUIConfig | None:
        if os.getenv("OPENWEBUI_SYNC_ENABLED", "").lower() in ("0", "false", "no"):
            return None

        base_url = (os.getenv("OPENWEBUI_BASE_URL") or "").strip().rstrip("/")
        api_key = (os.getenv("OPENWEBUI_API_KEY") or "").strip()
        knowledge_id = (os.getenv("OPENWEBUI_KNOWLEDGE_ID") or "").strip()
        if not (base_url and api_key and knowledge_id):
            return None

        timeout = float(os.getenv("OPENWEBUI_PROCESS_TIMEOUT_SEC", DEFAULT_PROCESS_TIMEOUT_SEC))
        return cls(
            base_url=base_url,
            api_key=api_key,
            knowledge_id=knowledge_id,
            process_timeout_sec=timeout,
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sync_cleanup_enabled() -> bool:
    """When true, remote KB files not in the local manifest are deleted (full mirror mode)."""
    return os.getenv("OPENWEBUI_SYNC_CLEANUP", "").lower() in ("1", "true", "yes")


def _sync_all_monthly_files() -> bool:
    """When true, push every monthly file the server diff wants (initial KB backfill)."""
    return os.getenv("OPENWEBUI_SYNC_ALL", "").lower() in ("1", "true", "yes")


def _manifest_for_api(manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "path": entry["path"],
            "filename": entry["filename"],
            "checksum": entry["checksum"],
            "size": entry["size"],
        }
        for entry in manifest
    ]


def _diff_file_entries(entries: list[Any] | None) -> list[dict[str, Any]]:
    """Normalize sync/diff added/modified entries to dicts with path + filename."""
    normalized: list[dict[str, Any]] = []
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("filename"):
            normalized.append(entry)
        elif isinstance(entry, str):
            # Legacy: treat string as store-relative file path
            normalized.append({"path": "", "filename": Path(entry).name})
    return normalized


def _diff_file_ids(entries: list[Any] | None) -> list[str]:
    ids: list[str] = []
    for entry in entries or []:
        if isinstance(entry, str):
            ids.append(entry)
        elif isinstance(entry, dict) and entry.get("file_id"):
            ids.append(str(entry["file_id"]))
    return ids


def _store_relpath_from_diff_entry(entry: dict[str, Any]) -> str:
    kb_dir = str(entry.get("path") or "")
    store_dir = strip_kb_folder_prefix(kb_dir)
    filename = str(entry.get("filename") or "")
    if store_dir:
        return f"{store_dir}/{filename}"
    return filename


def _replacement_file_ids(
    deleted_entries: list[Any] | None, upload_relpaths: set[str]
) -> list[str]:
    """Remote file IDs to remove before upload (same path, new checksum)."""
    ids: list[str] = []
    upload_names = {Path(p).name for p in upload_relpaths}
    for entry in deleted_entries or []:
        if not isinstance(entry, dict) or not entry.get("file_id"):
            continue
        store_rel = _store_relpath_from_diff_entry(entry)
        if store_rel in upload_relpaths or Path(store_rel).name in upload_names:
            ids.append(str(entry["file_id"]))
    return ids


def _is_activity_markdown(name: str) -> bool:
    return bool(
        ACTIVITY_FILE_PATTERN.match(name)
        or LEGACY_PER_ACTIVITY_FILE_PATTERN.match(name)
        or LEGACY_MONTHLY_FILE_PATTERN.match(name)
    )


def build_manifest(output_dir: Path) -> list[dict[str, Any]]:
    """Manifest for Open WebUI sync/diff (path relative to KB root)."""
    manifest: list[dict[str, Any]] = []
    if not output_dir.is_dir():
        return manifest

    for root, _, files in os.walk(output_dir):
        for name in sorted(files):
            if not name.endswith(".md") or not _is_activity_markdown(name):
                continue
            path = Path(root) / name
            if not path.is_file():
                continue
            store_relpath = path.relative_to(output_dir).as_posix()
            store_parent = path.parent.relative_to(output_dir).as_posix()
            if store_parent == ".":
                store_parent = ""
            manifest.append(
                {
                    # Open WebUI: path = KB directory, filename = basename (see sync/diff).
                    "path": knowledge_directory_path(store_parent),
                    "store_relpath": store_relpath,
                    "relpath": store_relpath,
                    "filename": name,
                    "checksum": sha256_file(path),
                    "size": path.stat().st_size,
                }
            )
    return manifest


def build_upload_metadata(
    manifest_entry: dict[str, Any],
    knowledge_id: str,
    directory_id_by_path: dict[str, str],
) -> dict[str, Any]:
    """Upload into the directory given by manifest ``path`` (e.g. ``Activities/2026/10``)."""
    metadata: dict[str, Any] = {
        "knowledge_id": knowledge_id,
        "file_hash": manifest_entry["checksum"],
        "filename": manifest_entry["filename"],
    }
    kb_dir = manifest_entry.get("path") or ""
    dir_id = directory_id_by_path.get(kb_dir)
    if dir_id:
        metadata["directory_id"] = dir_id
    return metadata


class OpenWebUIClient:
    def __init__(self, config: OpenWebUIConfig) -> None:
        self.config = config
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {config.api_key}",
                "Accept": "application/json",
            }
        )

    def _url(self, path: str) -> str:
        return f"{self.config.base_url}{path}"

    def sync_diff(self, manifest: list[dict[str, Any]]) -> dict[str, Any]:
        response = self._session.post(
            self._url(f"/api/v1/knowledge/{self.config.knowledge_id}/sync/diff"),
            json={"manifest": _manifest_for_api(manifest)},
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def create_directory(self, name: str, parent_id: str | None = None) -> str:
        body: dict[str, Any] = {"name": name}
        if parent_id:
            body["parent_id"] = parent_id
        response = self._session.post(
            self._url(f"/api/v1/knowledge/{self.config.knowledge_id}/dirs/create"),
            json=body,
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        dir_id = payload.get("id")
        if not dir_id:
            raise RuntimeError(f"Directory create response missing id: {payload}")
        return str(dir_id)

    def ensure_directories(self, diff: dict[str, Any]) -> dict[str, str]:
        """Create directories listed in diff.mkdir; return path → directory_id map."""
        directory_id_by_path: dict[str, str] = {
            str(k): str(v) for k, v in (diff.get("directory_map") or {}).items()
        }
        mkdir_paths = diff.get("mkdir") or []
        for dir_path in sorted((str(p) for p in mkdir_paths), key=lambda p: p.count("/")):
            if dir_path in directory_id_by_path:
                continue
            segments = dir_path.split("/")
            name = segments[-1]
            parent_path = "/".join(segments[:-1])
            parent_id = directory_id_by_path.get(parent_path) if parent_path else None
            directory_id_by_path[dir_path] = self.create_directory(name, parent_id)
            logger.info("Open WebUI: created directory %s", dir_path)
        return directory_id_by_path

    def resolve_directory_id(self, diff: dict[str, Any]) -> str | None:
        """Map OPENWEBUI_KB_FOLDER (or OPENWEBUI_KB_DIRECTORY_ID) to a knowledge directory id."""
        override = (os.getenv("OPENWEBUI_KB_DIRECTORY_ID") or "").strip()
        if override:
            return override

        folder = knowledge_folder_name()
        if not folder:
            return None

        directory_map = diff.get("directory_map") or {}
        if folder in directory_map:
            return str(directory_map[folder])
        for name, dir_id in directory_map.items():
            if str(name).lower() == folder.lower():
                return str(dir_id)
        return None

    def upload_file(
        self,
        file_path: Path,
        manifest_entry: dict[str, Any],
        directory_id_by_path: dict[str, str],
    ) -> str:
        metadata = build_upload_metadata(
            manifest_entry, self.config.knowledge_id, directory_id_by_path
        )
        with file_path.open("rb") as handle:
            response = self._session.post(
                self._url("/api/v1/files/"),
                files={"file": (manifest_entry["filename"], handle, "text/markdown")},
                data={"metadata": json.dumps(metadata)},
                timeout=120,
            )
        response.raise_for_status()
        payload = response.json()
        file_id = payload.get("id") or payload.get("file_id")
        if not file_id:
            raise RuntimeError(f"Upload response missing file id: {payload}")
        return str(file_id)

    def wait_until_processed(self, file_id: str) -> None:
        deadline = time.monotonic() + self.config.process_timeout_sec
        while time.monotonic() < deadline:
            response = self._session.get(
                self._url(f"/api/v1/files/{file_id}/process/status"),
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            status = (payload.get("status") or payload.get("state") or "").lower()
            if status in {"completed", "complete", "done", "success"}:
                return
            if status in {"failed", "error"}:
                raise RuntimeError(f"Open WebUI processing failed for {file_id}: {payload}")
            time.sleep(DEFAULT_POLL_INTERVAL_SEC)
        raise TimeoutError(f"Timed out waiting for Open WebUI to process file {file_id}")

    def sync_cleanup(self, file_ids: list[str], dir_ids: list[str]) -> None:
        if not file_ids and not dir_ids:
            return
        response = self._session.post(
            self._url(f"/api/v1/knowledge/{self.config.knowledge_id}/sync/cleanup"),
            json={"file_ids": file_ids, "dir_ids": dir_ids},
            timeout=60,
        )
        response.raise_for_status()


def paths_for_diff_entries(output_dir: Path, diff_entries: list[Any]) -> list[Path]:
    """Map sync/diff file entries (KB dir path + filename) to local files."""
    paths: list[Path] = []
    for entry in _diff_file_entries(diff_entries):
        filename = entry["filename"]
        kb_dir = entry.get("path") or ""
        store_dir = strip_kb_folder_prefix(str(kb_dir))
        local = (output_dir / store_dir / filename) if store_dir else (output_dir / filename)
        if local.is_file():
            paths.append(local)
    return paths


def sync_output_dir_to_knowledge(
    config: OpenWebUIConfig,
    output_dir: str | Path,
    touched_filenames: set[str] | frozenset[str] | None = None,
) -> dict[str, int]:
    """
    Sync activity Markdown files into Open WebUI.

    By default only uploads files written during this collect run (``touched_filenames`` as
    paths relative to the activity store, e.g. ``2026/10/running_123.md``).
    Set OPENWEBUI_SYNC_ALL=true to upload every file the server diff marks added/modified.

    Uses knowledge sync/diff (Open WebUI >= 0.9.6) when available.
    """
    output_dir = Path(output_dir)
    manifest = build_manifest(output_dir)
    if not manifest:
        logger.info("Open WebUI: no activity Markdown files to sync.")
        return {"uploaded": 0, "deleted": 0, "skipped": 0}

    client = OpenWebUIClient(config)
    manifest_by_relpath = {entry["relpath"]: entry for entry in manifest}

    try:
        diff = client.sync_diff(manifest)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            raise RuntimeError(
                "Open WebUI sync/diff endpoint not found; upgrade Open WebUI to >= 0.9.6 "
                "or check OPENWEBUI_KNOWLEDGE_ID."
            ) from exc
        raise RuntimeError(f"Open WebUI sync/diff failed: {_http_error_detail(exc)}") from exc

    try:
        directory_id_by_path = client.ensure_directories(diff)
    except requests.HTTPError as exc:
        raise RuntimeError(
            f"Open WebUI directory create failed: {_http_error_detail(exc)}"
        ) from exc

    diff_entries = _diff_file_entries(diff.get("added")) + _diff_file_entries(
        diff.get("modified")
    )
    to_upload_paths = paths_for_diff_entries(output_dir, diff_entries)
    seen_relpaths: set[str] = set()
    to_upload: list[Path] = []
    for path in to_upload_paths:
        relpath = path.relative_to(output_dir).as_posix()
        if relpath in seen_relpaths:
            continue
        seen_relpaths.add(relpath)
        to_upload.append(path)

    sync_all = _sync_all_monthly_files()
    if not sync_all and touched_filenames is not None:
        allow = set(touched_filenames)
        pending = len(to_upload)
        to_upload = [
            path
            for path in to_upload
            if path.relative_to(output_dir).as_posix() in allow or path.name in allow
        ]
        deferred = pending - len(to_upload)
        if deferred:
            logger.info(
                "Open WebUI: skipping %s remote-out-of-date file(s) "
                "(unchanged this run; set OPENWEBUI_SYNC_ALL=true for full KB backfill).",
                deferred,
            )
        if to_upload:
            names = ", ".join(sorted(p.relative_to(output_dir).as_posix() for p in to_upload))
            logger.info(
                "Open WebUI: pushing %s file(s) updated this collect run: %s",
                len(to_upload),
                names,
            )
    elif sync_all and to_upload:
        logger.info("Open WebUI: full sync — uploading %s file(s) from diff.", len(to_upload))

    upload_relpaths = {path.relative_to(output_dir).as_posix() for path in to_upload}
    all_deleted_ids = _diff_file_ids(diff.get("deleted"))
    replace_ids = _replacement_file_ids(diff.get("deleted"), upload_relpaths)
    other_deleted_ids = [fid for fid in all_deleted_ids if fid not in replace_ids]
    rmdir_ids = _diff_file_ids(diff.get("rmdir"))
    folder = knowledge_folder_name()
    if folder and folder in directory_id_by_path:
        logger.info(
            "Open WebUI: knowledge folder '%s' ready (directory_id=%s)",
            folder,
            directory_id_by_path[folder],
        )
    elif folder:
        logger.warning(
            "Open WebUI: folder '%s' missing from directory_map after mkdir; "
            "create it in the KB UI or set OPENWEBUI_KB_DIRECTORY_ID.",
            folder,
        )

    if not to_upload:
        unmodified = int(diff.get("unmodified_count", 0))
        logger.info("Open WebUI: nothing to upload (%s unchanged on server).", unmodified)
        return {"uploaded": 0, "deleted": 0, "skipped": unmodified}

    removed = 0
    if replace_ids:
        logger.info(
            "Open WebUI: removing %s superseded remote copie(s) for file(s) being uploaded...",
            len(replace_ids),
        )
        client.sync_cleanup(replace_ids, [])
        removed += len(replace_ids)

    upload_errors: list[str] = []
    uploaded = 0
    for path in to_upload:
        relpath = path.relative_to(output_dir).as_posix()
        entry = manifest_by_relpath.get(relpath)
        if not entry:
            logger.warning("Skipping upload; no manifest entry for %s", relpath)
            continue
        kb_dir = entry.get("path") or ""
        target = f"{kb_dir}/{entry['filename']}" if kb_dir else entry["filename"]
        logger.info("Open WebUI: uploading %s...", target)
        try:
            file_id = client.upload_file(path, entry, directory_id_by_path)
            client.wait_until_processed(file_id)
            uploaded += 1
        except requests.HTTPError as exc:
            upload_errors.append(
                f"{entry['path']}: {_http_error_detail(exc)}"
            )
        except (RuntimeError, TimeoutError) as exc:
            upload_errors.append(f"{entry['path']}: {exc}")

    if other_deleted_ids or rmdir_ids:
        if _sync_cleanup_enabled():
            logger.info(
                "Open WebUI: mirror cleanup of %s other file(s), %s directory(ies)...",
                len(other_deleted_ids),
                len(rmdir_ids),
            )
            client.sync_cleanup(other_deleted_ids, rmdir_ids)
            removed += len(other_deleted_ids)
        elif other_deleted_ids:
            logger.info(
                "Open WebUI: skipping mirror cleanup of %s non-Garmin file(s) "
                "(set OPENWEBUI_SYNC_CLEANUP=true to remove them).",
                len(other_deleted_ids),
            )

    unmodified = int(diff.get("unmodified_count", 0))
    logger.info(
        "Open WebUI sync done. Uploaded %s/%s, removed %s remote file(s), %s unchanged on server.",
        uploaded,
        len(to_upload),
        removed,
        unmodified,
    )
    if upload_errors:
        detail = "; ".join(upload_errors)
        raise RuntimeError(f"Open WebUI sync had upload/processing errors: {detail}")

    return {
        "uploaded": uploaded,
        "deleted": removed,
        "skipped": unmodified,
    }


def maybe_sync_to_openwebui(
    output_dir: str | Path,
    touched_filenames: set[str] | frozenset[str] | None = None,
) -> None:
    config = OpenWebUIConfig.from_env()
    if config is None:
        return
    if not _sync_all_monthly_files() and not touched_filenames:
        logger.info("Open WebUI: no activity files changed this run; skipping sync.")
        return
    logger.info("Open WebUI: syncing knowledge base %s...", config.knowledge_id)
    sync_output_dir_to_knowledge(config, output_dir, touched_filenames=touched_filenames)
