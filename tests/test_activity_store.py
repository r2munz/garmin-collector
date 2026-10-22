from garmin_collector.activity_store import (
    activity_filename,
    activity_month_key,
    activity_relpath,
    has_existing_activity_store,
    upsert_activity_file,
)
from garmin_collector.format_activity import SESSION_NOTES_HEADING, SESSION_NOTES_PLACEHOLDER

START = "2026-10-21 08:19:35"


def test_activity_month_key():
    assert activity_month_key("2026-01-15 08:00:00") == "2026-01"
    assert activity_month_key(None) is None


def test_activity_filename_and_relpath():
    assert activity_filename(START, "running") == "2026-10-21_08-19-35_running.md"
    assert activity_relpath("2026-10", START, "trail_running") == (
        "2026/10/2026-10-21_08-19-35_trail_running.md"
    )


def test_has_existing_activity_store(tmp_path):
    out = str(tmp_path)
    assert not has_existing_activity_store(out)
    (tmp_path / "activities_2026-01.md").write_text("# legacy\n", encoding="utf-8")
    assert has_existing_activity_store(out)
    (tmp_path / "activities_2026-01.md").unlink()
    nested = tmp_path / "2026" / "01"
    nested.mkdir(parents=True)
    (nested / "2026-01-15_08-00-00_running.md").write_text(
        "# run\n<!-- garmin-activity-id: 1 -->\n", encoding="utf-8"
    )
    assert has_existing_activity_store(out)


def test_upsert_creates_nested_file(tmp_path):
    out = str(tmp_path)
    body_v1 = "# Run\n<!-- garmin-activity-id: 42 -->\n\nVersion 1\n"
    body_v2 = "# Run\n<!-- garmin-activity-id: 42 -->\n\nVersion 2\n"

    action, relpath = upsert_activity_file(
        out, "2026-01", "42", "2026-01-10 06:00:00", "running", body_v1
    )
    assert action == "created"
    assert relpath == "2026/01/2026-01-10_06-00-00_running.md"
    path = tmp_path / "2026" / "01" / "2026-01-10_06-00-00_running.md"
    assert path.read_text(encoding="utf-8") == body_v1

    action, _ = upsert_activity_file(
        out, "2026-01", "42", "2026-01-10 06:00:00", "running", body_v2
    )
    assert action == "updated"
    assert "Version 2" in path.read_text(encoding="utf-8")


def test_upsert_preserves_session_notes(tmp_path):
    out = str(tmp_path)
    body_v1 = f"# Run\n<!-- garmin-activity-id: 7 -->\n\n{SESSION_NOTES_HEADING}My note.\n"
    body_v2 = "# Run\n<!-- garmin-activity-id: 7 -->\n\nFresh stats.\n"

    upsert_activity_file(out, "2026-02", "7", "2026-02-03 09:00:00", "yoga", body_v1)
    upsert_activity_file(out, "2026-02", "7", "2026-02-03 09:00:00", "yoga", body_v2)

    content = (tmp_path / "2026" / "02" / "2026-02-03_09-00-00_yoga.md").read_text(
        encoding="utf-8"
    )
    assert "My note." in content
    assert "Fresh stats." in content
    assert SESSION_NOTES_PLACEHOLDER not in content


def test_upsert_moves_month_folder(tmp_path):
    out = str(tmp_path)
    jan = "# Old\n<!-- garmin-activity-id: 5 -->\n\nJan\n"
    feb = "# New\n<!-- garmin-activity-id: 5 -->\n\nFeb\n"

    upsert_activity_file(out, "2026-01", "5", "2026-01-01 08:00:00", "running", jan)
    upsert_activity_file(out, "2026-02", "5", "2026-02-01 08:00:00", "running", feb)

    assert not (tmp_path / "2026" / "01" / "2026-01-01_08-00-00_running.md").exists()
    assert "Feb" in (tmp_path / "2026" / "02" / "2026-02-01_08-00-00_running.md").read_text(
        encoding="utf-8"
    )
