from pathlib import Path
from unittest.mock import MagicMock, patch

from garmin_collector.openwebui_sync import (
    OpenWebUIConfig,
    _diff_file_ids,
    _diff_paths,
    _replacement_file_ids,
    build_manifest,
    paths_for_diff_names,
    sha256_file,
    sync_output_dir_to_knowledge,
)


def test_diff_path_and_file_id_helpers():
    assert _diff_paths([{"path": "Activites/a.md"}]) == ["Activites/a.md"]
    assert _diff_file_ids([{"file_id": "abc"}]) == ["abc"]
    assert _replacement_file_ids(
        [
            {"file_id": "old-jan", "filename": "activities_2026-01.md"},
            {"file_id": "profile", "filename": "Profilo.md"},
        ],
        {"activities_2026-01.md"},
    ) == ["old-jan"]


def test_paths_for_diff_names_with_dict_entries(tmp_path):
    md = tmp_path / "activities_2026-01.md"
    md.write_text("x", encoding="utf-8")
    found = paths_for_diff_names(
        tmp_path, [{"path": "Activites/activities_2026-01.md"}]
    )
    assert found == [md]


def test_sha256_file_and_manifest(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENWEBUI_KB_FOLDER", raising=False)
    md = tmp_path / "activities_2026-01.md"
    md.write_text("# test\n", encoding="utf-8")
    checksum = sha256_file(md)
    assert len(checksum) == 64
    manifest = build_manifest(tmp_path)
    assert manifest == [
        {
            "path": "activities_2026-01.md",
            "filename": "activities_2026-01.md",
            "checksum": checksum,
            "size": md.stat().st_size,
        }
    ]


def test_build_manifest_with_kb_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENWEBUI_KB_FOLDER", "Activites")
    md = tmp_path / "activities_2026-01.md"
    md.write_text("# test\n", encoding="utf-8")
    manifest = build_manifest(tmp_path)
    assert manifest[0]["path"] == "Activites/activities_2026-01.md"
    assert manifest[0]["filename"] == "activities_2026-01.md"


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
    monkeypatch.delenv("OPENWEBUI_KB_FOLDER", raising=False)
    md = tmp_path / "activities_2026-01.md"
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
        "modified": ["activities_2026-01.md"],
        "deleted": [],
        "rmdir": [],
        "unmodified_count": 0,
    }
    mock_client.upload_file.return_value = "file-99"
    mock_client.wait_until_processed.return_value = None
    mock_client.sync_cleanup.return_value = None
    mock_client.resolve_directory_id.return_value = "dir-1"

    with patch(
        "garmin_collector.openwebui_sync.OpenWebUIClient",
        return_value=mock_client,
    ):
        stats = sync_output_dir_to_knowledge(
            config, tmp_path, touched_filenames={"activities_2026-01.md"}
        )

    assert stats["uploaded"] == 1
    mock_client.upload_file.assert_called_once()
    mock_client.wait_until_processed.assert_called_once_with("file-99")


def test_sync_only_touched_months(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENWEBUI_KB_FOLDER", raising=False)
    monkeypatch.delenv("OPENWEBUI_SYNC_ALL", raising=False)
    jan = tmp_path / "activities_2026-01.md"
    oct_ = tmp_path / "activities_2026-10.md"
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
        "added": ["activities_2026-01.md", "activities_2026-10.md"],
        "modified": [],
        "deleted": [
            {"file_id": "old-jan", "filename": "activities_2026-01.md"},
            {"file_id": "old-oct", "filename": "activities_2026-10.md"},
        ],
        "rmdir": [],
        "unmodified_count": 0,
    }
    mock_client.upload_file.return_value = "file-oct"
    mock_client.wait_until_processed.return_value = None
    mock_client.sync_cleanup.return_value = None
    mock_client.resolve_directory_id.return_value = None

    with patch(
        "garmin_collector.openwebui_sync.OpenWebUIClient",
        return_value=mock_client,
    ):
        stats = sync_output_dir_to_knowledge(
            config, tmp_path, touched_filenames={"activities_2026-10.md"}
        )

    assert stats["uploaded"] == 1
    mock_client.sync_cleanup.assert_called_once_with(["old-oct"], [])
    mock_client.upload_file.assert_called_once()
    assert mock_client.upload_file.call_args[0][0] == oct_
