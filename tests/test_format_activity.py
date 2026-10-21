from garmin_collector.format_activity import (
    SESSION_NOTES_PLACEHOLDER,
    _weather_temp,
    format_activity_section,
    format_pace_per_km,
    format_time,
    format_weather_block,
    merge_session_notes,
)


def test_format_time():
    assert format_time(None) == "00:00:00"
    assert format_time(3661) == "01:01:01"


def test_format_pace_per_km():
    assert format_pace_per_km(300, 1000) == "5:00/km"
    assert format_pace_per_km(0, 0) == "—"


def test_weather_temp_metric_converts_from_fahrenheit():
    assert _weather_temp(32, "metric") == "0.0 °C"
    assert _weather_temp(35, "metric") == "1.7 °C"


def test_weather_temp_imperial():
    assert _weather_temp(35, "imperial") == "35.0 °F"


def test_format_weather_block_null_wind_compass():
    lines = format_weather_block(
        {
            "temp": 40,
            "apparentTemp": 38,
            "relativeHumidity": 50,
            "windSpeed": 2,
            "windDirectionCompassPoint": None,
            "windDirection": None,
            "weatherTypeDTO": {"desc": "Cloudy"},
        },
        "metric",
    )
    text = "\n".join(lines)
    assert "from —" in text
    assert ".upper" not in text


def test_merge_session_notes_keeps_user_text():
    old = f"## Run\n\n### Session notes\nLegs felt heavy.\n"
    new = f"## Run\n\n### Session notes\n{SESSION_NOTES_PLACEHOLDER}\n"
    merged = merge_session_notes(old, new)
    assert "Legs felt heavy." in merged
    assert SESSION_NOTES_PLACEHOLDER not in merged


def test_merge_session_notes_uses_placeholder_when_unchanged():
    old = f"## Run\n\n### Session notes\n{SESSION_NOTES_PLACEHOLDER}\n"
    new = f"## Run\n\n### Session notes\n{SESSION_NOTES_PLACEHOLDER}\n"
    assert merge_session_notes(old, new) == new


def test_format_activity_section_includes_marker_and_snapshot():
    act = {
        "activityId": 99,
        "activityName": "Test Run",
        "startTimeLocal": "2026-03-15 10:00:00",
        "distance": 5000,
        "duration": 1800,
        "averageHR": 140,
        "maxHR": 155,
        "elevationGain": 50.0,
        "elevationLoss": 40.0,
        "activityType": {"typeKey": "running"},
    }
    enrichment = {
        "weather": {
            "temp": 50,
            "apparentTemp": 48,
            "relativeHumidity": 60,
            "windSpeed": 3,
            "windDirection": 90,
            "windDirectionCompassPoint": "e",
            "weatherTypeDTO": {"desc": "Clear"},
        },
        "gear": [{"gearTypeName": "Shoes", "customMakeModel": "Test Shoe"}],
        "hr_zones": [{"zoneNumber": 1, "secsInZone": 100, "zoneLowBoundary": 90}],
        "power_zones": [],
        "splits": {
            "lapDTOs": [
                {
                    "lapIndex": 1,
                    "distance": 1000.0,
                    "duration": 360.0,
                    "elevationGain": 10.0,
                    "averageHR": 130,
                }
            ]
        },
    }
    text = format_activity_section(
        act, enrichment, "metric", synced_at="2026-01-01T00:00:00Z"
    )
    assert "<!-- garmin-activity-id: 99 -->" in text
    assert "### Agent snapshot" in text
    assert '"activity_id": 99' in text
    assert "Test Shoe" in text
    assert "5.00 km" in text
