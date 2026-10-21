from datetime import date

import pytest

from garmin_collector.main import parse_iso_date, resolve_sync_window, start_of_current_year


def test_parse_iso_date():
    assert parse_iso_date("2026-03-01") == date(2026, 3, 1)
    assert parse_iso_date("") is None
    assert parse_iso_date(None) is None


def test_start_of_current_year():
    assert start_of_current_year(date(2026, 7, 4)) == date(2026, 1, 1)


def test_resolve_sync_window_env_override(tmp_path, monkeypatch):
    monkeypatch.delenv("SYNC_START", raising=False)
    monkeypatch.delenv("SYNC_END", raising=False)
    monkeypatch.setenv("SYNC_START", "2026-02-01")
    monkeypatch.setenv("SYNC_END", "2026-02-10")

    start, end = resolve_sync_window(str(tmp_path), today=date(2026, 6, 1))
    assert start == date(2026, 2, 1)
    assert end == date(2026, 2, 10)


def test_resolve_sync_window_first_sync(tmp_path, monkeypatch):
    monkeypatch.delenv("SYNC_START", raising=False)
    monkeypatch.delenv("SYNC_END", raising=False)
    monkeypatch.delenv("SYNC_LOOKBACK_DAYS", raising=False)

    start, end = resolve_sync_window(str(tmp_path), today=date(2026, 6, 15))
    assert start == date(2026, 1, 1)
    assert end == date(2026, 6, 15)


def test_resolve_sync_window_incremental(tmp_path, monkeypatch):
    (tmp_path / "activities_2026-01.md").write_text("# x\n", encoding="utf-8")
    monkeypatch.delenv("SYNC_START", raising=False)
    monkeypatch.delenv("SYNC_END", raising=False)
    monkeypatch.setenv("SYNC_LOOKBACK_DAYS", "7")

    start, end = resolve_sync_window(str(tmp_path), today=date(2026, 6, 15))
    assert end == date(2026, 6, 15)
    assert start == date(2026, 6, 8)


def test_resolve_sync_window_invalid_range(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNC_START", "2026-06-10")
    monkeypatch.setenv("SYNC_END", "2026-06-01")
    with pytest.raises(ValueError, match="SYNC_START"):
        resolve_sync_window(str(tmp_path), today=date(2026, 6, 15))
