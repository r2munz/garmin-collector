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

from garmin_collector.monthly_store import MONTHLY_FILE_PATTERN
from garmin_collector.paths import knowledge_folder_name, knowledge_relative_path

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


def _diff_paths(entries: list[Any] | None) -> list[str]:
    paths: list[str] = []
    for entry in entries or []:
        if isinstance(entry, str):
            paths.append(entry)
        elif isinstance(entry, dict):
            value = entry.get("path") or entry.get("filename")
            if value:
                paths.append(str(value))
    return paths


def _diff_file_ids(entries: list[Any] | None) -> list[str]:
    ids: list[str] = []
    for entry in entries or []:
        if isinstance(entry, str):
            ids.append(entry)
        elif isinstance(entry, dict) and entry.get("file_id"):
            ids.append(str(entry["file_id"]))
    return ids


def _replacement_file_ids(
    deleted_entries: list[Any] | None, manifest_filenames: set[str]
) -> list[str]:
    """Remote file IDs to remove before upload (same monthly name, new checksum)."""
    ids: list[str] = []
    for entry in deleted_entries or []:
        if not isinstance(entry, dict) or not entry.get("file_id"):
            continue
        name = entry.get("filename") or Path(str(entry.get("path", ""))).name
        if name in manifest_filenames:
            ids.append(str(entry["file_id"]))
    return ids


def build_manifest(output_dir: Path) -> list[dict[str, Any]]:
    """Manifest for Open WebUI sync/diff (path relative to KB root)."""
    manifest: list[dict[str, str]] = []
    if not output_dir.is_dir():
        return manifest

    for name in sorted(os.listdir(output_dir)):
        if not MONTHLY_FILE_PATTERN.match(name):
            continue
        path = output_dir / name
        if not path.is_file():
            continue
        manifest.append(
            {
                "path": knowledge_relative_path(name),
                "filename": name,
                "checksum": sha256_file(path),
                "size": path.stat().st_size,
            }
        )
    return manifest


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

    def sync_diff(self, manifest: list[dict[str, str]]) -> dict[str, Any]:
        response = self._session.post(
            self._url(f"/api/v1/knowledge/{self.config.knowledge_id}/sync/diff"),
            json={"manifest": manifest},
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

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
        directory_id: str | None = None,
    ) -> str:
        metadata: dict[str, Any] = {
            "knowledge_id": self.config.knowledge_id,
            "file_hash": manifest_entry["checksum"],
            "filename": manifest_entry["filename"],
        }
        if directory_id:
            # Open WebUI places the file inside the folder when directory_id is set.
            metadata["directory_id"] = directory_id
            metadata["path"] = manifest_entry["filename"]
        else:
            metadata["path"] = manifest_entry["path"]
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


def paths_for_diff_names(output_dir: Path, diff_entries: list[Any]) -> list[Path]:
    """Map KB-relative paths from sync/diff to local files in output_dir."""
    paths: list[Path] = []
    for rel_path in _diff_paths(diff_entries):
        local = output_dir / Path(rel_path).name
        if local.is_file():
            paths.append(local)
    return paths


def sync_output_dir_to_knowledge(
    config: OpenWebUIConfig,
    output_dir: str | Path,
    touched_filenames: set[str] | frozenset[str] | None = None,
) -> dict[str, int]:
    """
    Sync monthly Markdown files into Open WebUI.

    By default only uploads months written during this collect run (``touched_filenames``).
    Set OPENWEBUI_SYNC_ALL=true to upload every file the server diff marks added/modified.

    Uses knowledge sync/diff (Open WebUI >= 0.9.6) when available.
    """
    output_dir = Path(output_dir)
    manifest = build_manifest(output_dir)
    if not manifest:
        print("Open WebUI: no monthly Markdown files to sync.")
        return {"uploaded": 0, "deleted": 0, "skipped": 0}

    client = OpenWebUIClient(config)
    manifest_by_filename = {entry["filename"]: entry for entry in manifest}

    try:
        diff = client.sync_diff(manifest)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            raise RuntimeError(
                "Open WebUI sync/diff endpoint not found; upgrade Open WebUI to >= 0.9.6 "
                "or check OPENWEBUI_KNOWLEDGE_ID."
            ) from exc
        raise RuntimeError(f"Open WebUI sync/diff failed: {_http_error_detail(exc)}") from exc

    to_upload_paths = paths_for_diff_names(
        output_dir,
        _diff_paths(diff.get("added")) + _diff_paths(diff.get("modified")),
    )
    seen_names: set[str] = set()
    to_upload: list[Path] = []
    for path in to_upload_paths:
        if path.name in seen_names:
            continue
        seen_names.add(path.name)
        to_upload.append(path)

    sync_all = _sync_all_monthly_files()
    if not sync_all and touched_filenames is not None:
        allow = set(touched_filenames)
        pending = len(to_upload)
        to_upload = [path for path in to_upload if path.name in allow]
        deferred = pending - len(to_upload)
        if deferred:
            print(
                f"Open WebUI: skipping {deferred} remote-out-of-date month(s) "
                "(unchanged this run; set OPENWEBUI_SYNC_ALL=true for full KB backfill)."
            )
        if to_upload:
            names = ", ".join(sorted(p.name for p in to_upload))
            print(f"Open WebUI: pushing {len(to_upload)} file(s) updated this collect run: {names}")
    elif sync_all and to_upload:
        print(f"Open WebUI: full sync — uploading {len(to_upload)} file(s) from diff.")

    upload_filenames = {path.name for path in to_upload}
    all_deleted_ids = _diff_file_ids(diff.get("deleted"))
    replace_ids = _replacement_file_ids(diff.get("deleted"), upload_filenames)
    other_deleted_ids = [fid for fid in all_deleted_ids if fid not in replace_ids]
    rmdir_ids = _diff_file_ids(diff.get("rmdir"))
    directory_id = client.resolve_directory_id(diff)
    folder = knowledge_folder_name()
    if folder and directory_id:
        print(f"Open WebUI: target folder '{folder}' (directory_id={directory_id})")
    elif folder and not directory_id:
        print(
            f"Open WebUI: warning — folder '{folder}' not found in directory_map; "
            "files may land at knowledge root. Set OPENWEBUI_KB_DIRECTORY_ID if needed."
        )

    if not to_upload:
        unmodified = int(diff.get("unmodified_count", 0))
        print(f"Open WebUI: nothing to upload ({unmodified} unchanged on server).")
        return {"uploaded": 0, "deleted": 0, "skipped": unmodified}

    removed = 0
    if replace_ids:
        print(
            f"Open WebUI: removing {len(replace_ids)} superseded remote copie(s) "
            f"for file(s) being uploaded..."
        )
        client.sync_cleanup(replace_ids, [])
        removed += len(replace_ids)

    upload_errors: list[str] = []
    uploaded = 0
    for path in to_upload:
        entry = manifest_by_filename.get(path.name)
        if not entry:
            logger.warning("Skipping upload; no manifest entry for %s", path.name)
            continue
        target = f"{folder}/{entry['filename']}" if folder else entry["path"]
        print(f"Open WebUI: uploading {target}...")
        try:
            file_id = client.upload_file(path, entry, directory_id=directory_id)
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
            print(
                f"Open WebUI: mirror cleanup of {len(other_deleted_ids)} other file(s), "
                f"{len(rmdir_ids)} directory(ies)..."
            )
            client.sync_cleanup(other_deleted_ids, rmdir_ids)
            removed += len(other_deleted_ids)
        elif other_deleted_ids:
            print(
                "Open WebUI: skipping mirror cleanup of "
                f"{len(other_deleted_ids)} non-Garmin file(s) "
                "(set OPENWEBUI_SYNC_CLEANUP=true to remove them)."
            )

    unmodified = int(diff.get("unmodified_count", 0))
    print(
        f"Open WebUI sync done. Uploaded {uploaded}/{len(to_upload)}, "
        f"removed {removed} remote file(s), {unmodified} unchanged on server."
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
        print("Open WebUI: no monthly files changed this run; skipping sync.")
        return
    print(f"Open WebUI: syncing knowledge base {config.knowledge_id}...")
    sync_output_dir_to_knowledge(config, output_dir, touched_filenames=touched_filenames)
