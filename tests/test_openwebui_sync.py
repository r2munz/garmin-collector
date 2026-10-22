from pathlib import Path
from unittest.mock import MagicMock, patch

from garmin_collector.openwebui_sync import (
    OpenWebUIConfig,
    _diff_file_ids,
    _replacement_file_ids,
    build_manifest,
    build_upload_metadata,
    paths_for_diff_entries,
    sha256_file,
    sync_output_dir_to_knowledge,
)


def test_build_upload_metadata_uses_directory_map():
    entry = {
        "path": "Activities/2026/10",
        "filename": "2026-10-01_06-21-40_breathwork.md",
        "checksum": "abc",
    }
    meta = build_upload_metadata(entry, "kb-1", {"Activities/2026/10": "dir-oct"})
    assert meta["directory_id"] == "dir-oct"
    assert meta["filename"] == entry["filename"]


def test_build_manifest_splits_directory_and_filename(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENWEBUI_KB_FOLDER", "Activities")
    md = tmp_path / "2026" / "10" / "2026-10-01_06-21-40_breathwork.md"
    md.parent.mkdir(parents=True)
    md.write_text("# test\n", encoding="utf-8")
    manifest = build_manifest(tmp_path)
    assert manifest[0]["path"] == "Activities/2026/10"
    assert manifest[0]["filename"] == "2026-10-01_06-21-40_breathwork.md"
    assert manifest[0]["store_relpath"] == "2026/10/2026-10-01_06-21-40_breathwork.md"


def test_paths_for_diff_entries_nested(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENWEBUI_KB_FOLDER", "Activities")
    md = tmp_path / "2026" / "10" / "2026-10-21_08-00-00_running.md"
    md.parent.mkdir(parents=True)
    md.write_text("x", encoding="utf-8")
    found = paths_for_diff_entries(
        tmp_path,
        [{"path": "Activities/2026/10", "filename": "2026-10-21_08-00-00_running.md"}],
    )
    assert found == [md]


def test_replacement_file_ids_matches_store_relpath():
    assert _replacement_file_ids(
        [
            {"file_id": "old", "path": "Activities/2026/10", "filename": "a.md"},
            {"file_id": "profile", "path": "", "filename": "Profilo.md"},
        ],
        {"2026/10/a.md"},
    ) == ["old"]


def test_diff_file_ids_helper():
    assert _diff_file_ids([{"file_id": "abc"}]) == ["abc"]


def test_openwebui_config_from_env(monkeypatch):
    for key in (
        "OPENWEBUI_SYNC_ENABLED",
        "OPENWEBUI_BASE_URL",
        "OPENWEBUI_API_KEY",
        "OPENWEBUI_KNOWLEDGE_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    assert OpenWebUIConfig.from_env() is None

    monkeypatch.setenv("OPENWEBUI_BASE_URL", "http://localhost:3000")
    monkeypatch.setenv("OPENWEBUI_API_KEY", "secret")
    monkeypatch.setenv("OPENWEBUI_KNOWLEDGE_ID", "kb-1")
    cfg = OpenWebUIConfig.from_env()
    assert cfg is not None
    assert cfg.knowledge_id == "kb-1"

    monkeypatch.setenv("OPENWEBUI_SYNC_ENABLED", "false")
    assert OpenWebUIConfig.from_env() is None


def test_sync_output_dir_uploads_modified(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENWEBUI_KB_FOLDER", "Activities")
    md = tmp_path / "2026" / "01" / "2026-01-15_08-00-00_running.md"
    md.parent.mkdir(parents=True)
    md.write_text("# Activities\n", encoding="utf-8")
    config = OpenWebUIConfig(
        base_url="http://owui.test",
        api_key="token",
        knowledge_id="kb-1",
        process_timeout_sec=5,
    )

    mock_client = MagicMock()
    mock_client.sync_diff.return_value = {
        "added": [],
        "modified": [
            {
                "path": "Activities/2026/01",
                "filename": "2026-01-15_08-00-00_running.md",
            }
        ],
        "deleted": [],
        "mkdir": [],
        "rmdir": [],
        "directory_map": {"Activities/2026/01": "dir-jan"},
        "unmodified_count": 0,
    }
    mock_client.ensure_directories.return_value = {"Activities/2026/01": "dir-jan"}
    mock_client.upload_file.return_value = "file-99"
    mock_client.wait_until_processed.return_value = None
    mock_client.sync_cleanup.return_value = None

    with patch(
        "garmin_collector.openwebui_sync.OpenWebUIClient",
        return_value=mock_client,
    ):
        stats = sync_output_dir_to_knowledge(
            config,
            tmp_path,
            touched_filenames={"2026/01/2026-01-15_08-00-00_running.md"},
        )

    assert stats["uploaded"] == 1
    mock_client.ensure_directories.assert_called_once()
    mock_client.upload_file.assert_called_once()
    mock_client.wait_until_processed.assert_called_once_with("file-99")


def test_sync_only_touched_files(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENWEBUI_KB_FOLDER", "Activities")
    monkeypatch.delenv("OPENWEBUI_SYNC_ALL", raising=False)
    jan = tmp_path / "2026" / "01" / "2026-01-05_12-00-00_running.md"
    oct_ = tmp_path / "2026" / "10" / "2026-10-21_08-00-00_running.md"
    jan.parent.mkdir(parents=True)
    oct_.parent.mkdir(parents=True)
    jan.write_text("jan", encoding="utf-8")
    oct_.write_text("oct", encoding="utf-8")
    config = OpenWebUIConfig(
        base_url="http://owui.test",
        api_key="token",
        knowledge_id="kb-1",
        process_timeout_sec=5,
    )

    mock_client = MagicMock()
    mock_client.sync_diff.return_value = {
        "added": [
            {"path": "Activities/2026/01", "filename": "2026-01-05_12-00-00_running.md"},
            {"path": "Activities/2026/10", "filename": "2026-10-21_08-00-00_running.md"},
        ],
        "modified": [],
        "deleted": [
            {
                "file_id": "old-oct",
                "path": "Activities/2026/10",
                "filename": "2026-10-21_08-00-00_running.md",
            },
        ],
        "mkdir": [],
        "rmdir": [],
        "directory_map": {
            "Activities/2026/01": "d1",
            "Activities/2026/10": "d2",
        },
        "unmodified_count": 0,
    }
    mock_client.ensure_directories.return_value = mock_client.sync_diff.return_value[
        "directory_map"
    ]
    mock_client.upload_file.return_value = "file-oct"
    mock_client.wait_until_processed.return_value = None
    mock_client.sync_cleanup.return_value = None

    with patch(
        "garmin_collector.openwebui_sync.OpenWebUIClient",
        return_value=mock_client,
    ):
        stats = sync_output_dir_to_knowledge(
            config,
            tmp_path,
            touched_filenames={"2026/10/2026-10-21_08-00-00_running.md"},
        )

    assert stats["uploaded"] == 1
    mock_client.sync_cleanup.assert_called_once_with(["old-oct"], [])
    mock_client.upload_file.assert_called_once()
    assert mock_client.upload_file.call_args[0][0] == oct_
