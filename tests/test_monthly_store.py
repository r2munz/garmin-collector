from garmin_collector.format_activity import SESSION_NOTES_PLACEHOLDER
from garmin_collector.monthly_store import (
    _parse_monthly_content,
    _render_monthly_file,
    activity_month_key,
    has_existing_monthly_store,
    monthly_file_header,
    upsert_activity_section,
)


def test_activity_month_key():
    assert activity_month_key("2026-01-15 08:00:00") == "2026-01"
    assert activity_month_key(None) is None
    assert activity_month_key("not-a-date") is None


def test_parse_and_render_roundtrip():
    preamble = monthly_file_header("2026-01")
    section_a = "## Run A\n<!-- garmin-activity-id: 1 -->\n\nBody A\n"
    section_b = "## Run B\n<!-- garmin-activity-id: 2 -->\n\nBody B\n"
    raw = _render_monthly_file(preamble, [("1", section_a), ("2", section_b)])

    parsed_preamble, sections = _parse_monthly_content(raw)
    assert "January 2026" in parsed_preamble
    assert [aid for aid, _ in sections] == ["1", "2"]
    assert "Body A" in sections[0][1]


def test_has_existing_monthly_store(tmp_path):
    assert not has_existing_monthly_store(str(tmp_path))
    (tmp_path / "activities_2026-01.md").write_text("# x\n", encoding="utf-8")
    assert has_existing_monthly_store(str(tmp_path))


def test_upsert_creates_then_updates(tmp_path):
    out = str(tmp_path)
    section_v1 = "## Run\n<!-- garmin-activity-id: 42 -->\n\nVersion 1\n"
    section_v2 = "## Run\n<!-- garmin-activity-id: 42 -->\n\nVersion 2\n"

    assert upsert_activity_section(out, "2026-01", "42", section_v1) == "created"
    path = tmp_path / "activities_2026-01.md"
    content = path.read_text(encoding="utf-8")
    assert "Version 1" in content
    assert content.count("<!-- garmin-activity-id: 42 -->") == 1

    assert upsert_activity_section(out, "2026-01", "42", section_v2) == "updated"
    content = path.read_text(encoding="utf-8")
    assert "Version 2" in content
    assert "Version 1" not in content


def test_upsert_preserves_session_notes_on_update(tmp_path):
    out = str(tmp_path)
    section_v1 = (
        "## Run\n<!-- garmin-activity-id: 7 -->\n\n### Session notes\nMy note.\n"
    )
    section_v2 = (
        f"## Run\n<!-- garmin-activity-id: 7 -->\n\n### Session notes\n"
        f"{SESSION_NOTES_PLACEHOLDER}\n"
    )

    upsert_activity_section(out, "2026-02", "7", section_v1)
    upsert_activity_section(out, "2026-02", "7", section_v2)

    content = (tmp_path / "activities_2026-02.md").read_text(encoding="utf-8")
    assert "My note." in content


def test_render_sorts_sections_by_activity_start_time(tmp_path):
    preamble = monthly_file_header("2026-10")
    early = (
        "## Early\n<!-- garmin-activity-id: 1 -->\n\n"
        "### Summary\n- **Date and time (local):** 2026-10-01 08:00:00\n"
    )
    late = (
        "## Late\n<!-- garmin-activity-id: 2 -->\n\n"
        "### Summary\n- **Date and time (local):** 2026-10-21 08:00:00\n"
    )
    raw = _render_monthly_file(preamble, [("2", late), ("1", early)])
    _, sections = _parse_monthly_content(raw)
    assert [aid for aid, _ in sections] == ["1", "2"]


def test_upsert_moves_activity_between_months(tmp_path):
    out = str(tmp_path)
    jan_section = "## Old\n<!-- garmin-activity-id: 5 -->\n\nJan\n"
    feb_section = "## New\n<!-- garmin-activity-id: 5 -->\n\nFeb\n"

    upsert_activity_section(out, "2026-01", "5", jan_section)
    upsert_activity_section(out, "2026-02", "5", feb_section)

    jan = (tmp_path / "activities_2026-01.md").read_text(encoding="utf-8")
    feb = (tmp_path / "activities_2026-02.md").read_text(encoding="utf-8")
    assert "garmin-activity-id: 5" not in jan
    assert "Feb" in feb
