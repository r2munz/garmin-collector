from pathlib import Path

from garmin_collector.paths import resolve_output_dir


def _clear_openwebui_path_env(monkeypatch):
    for key in ("OPENWEBUI_KNOWLEDGE_ID", "OPENWEBUI_KB_FOLDER", "OPENWEBUI_KB_SUBDIR"):
        monkeypatch.delenv(key, raising=False)


def test_resolve_output_dir_plain(monkeypatch):
    _clear_openwebui_path_env(monkeypatch)
    monkeypatch.setenv("OUTPUT_DIR", "./data")
    assert Path(resolve_output_dir()) == Path("./data")


def test_resolve_output_dir_kb_subdir_default(monkeypatch):
    _clear_openwebui_path_env(monkeypatch)
    monkeypatch.setenv("OUTPUT_DIR", "./data")
    monkeypatch.setenv("OPENWEBUI_KNOWLEDGE_ID", "kb-abc-123")
    assert Path(resolve_output_dir()) == Path("./data") / "kb-abc-123"


def test_resolve_output_dir_kb_subdir_disabled(monkeypatch):
    _clear_openwebui_path_env(monkeypatch)
    monkeypatch.setenv("OUTPUT_DIR", "./data")
    monkeypatch.setenv("OPENWEBUI_KNOWLEDGE_ID", "kb-abc-123")
    monkeypatch.setenv("OPENWEBUI_KB_SUBDIR", "false")
    assert Path(resolve_output_dir()) == Path("./data")


def test_resolve_output_dir_with_kb_folder(monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", "./data")
    monkeypatch.setenv("OPENWEBUI_KNOWLEDGE_ID", "kb-1")
    monkeypatch.setenv("OPENWEBUI_KB_FOLDER", "Activites")
    assert Path(resolve_output_dir()) == Path("./data") / "kb-1" / "Activites"


def test_knowledge_relative_path(monkeypatch):
    from garmin_collector.paths import knowledge_directory_path, knowledge_relative_path

    monkeypatch.delenv("OPENWEBUI_KB_FOLDER", raising=False)
    assert knowledge_relative_path("activities_2026-01.md") == "activities_2026-01.md"
    monkeypatch.setenv("OPENWEBUI_KB_FOLDER", "Activities")
    assert knowledge_relative_path("2026/10/foo.md") == "Activities/2026/10/foo.md"
    assert knowledge_directory_path("2026/10") == "Activities/2026/10"
