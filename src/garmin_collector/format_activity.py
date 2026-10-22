"""Format Garmin activity data for Markdown / agent consumption."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

SESSION_NOTES_PLACEHOLDER = "*(Add recovery or subjective notes here.)*"
SESSION_NOTES_HEADING = "### Session notes\n"
ACTIVITY_ID_MARKER = re.compile(r"<!--\s*garmin-activity-id:\s*(\d+)\s*-->")


def format_time(seconds: float | int | None) -> str:
    if not seconds:
        return "00:00:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_pace_per_km(duration_sec: float, distance_m: float) -> str:
    if not distance_m or distance_m <= 0:
        return "—"
    sec_per_km = duration_sec / (distance_m / 1000.0)
    minutes, seconds = divmod(int(sec_per_km), 60)
    return f"{minutes}:{seconds:02d}/km"


def format_pace_per_mile(duration_sec: float, distance_m: float) -> str:
    if not distance_m or distance_m <= 0:
        return "—"
    sec_per_mile = duration_sec / (distance_m / 1609.344)
    minutes, seconds = divmod(int(sec_per_mile), 60)
    return f"{minutes}:{seconds:02d}/mi"


def _weather_temp(value: float | int | None, unit_system: str | None) -> str:
    if value is None:
        return "—"
    # Activity weather from Garmin Connect is reported in Fahrenheit.
    if unit_system == "metric":
        celsius = (float(value) - 32) * 5 / 9
        return f"{celsius:.1f} °C"
    return f"{float(value):.1f} °F"


def _wind_speed(value: float | int | None, unit_system: str | None) -> str:
    if value is None:
        return "—"
    if unit_system == "metric":
        return f"{float(value):.1f} m/s"
    return f"{float(value):.1f} mph"


def _weather_compass(point: str | None) -> str:
    if point is None or str(point).strip() == "":
        return "—"
    return str(point).upper()


def format_weather_block(weather: dict[str, Any] | None, unit_system: str | None) -> list[str]:
    if not weather:
        return ["_No weather data from Garmin._"]

    wtype = weather.get("weatherTypeDTO") or {}
    condition = wtype.get("desc") or wtype.get("weatherTypePk") or "—"
    wind_dir = weather.get("windDirection")
    wind_dir_label = f"{wind_dir}°" if wind_dir is not None else "—"
    lines = [
        f"- **Conditions:** {condition}",
        f"- **Temperature:** {_weather_temp(weather.get('temp'), unit_system)}",
        f"- **Feels like:** {_weather_temp(weather.get('apparentTemp'), unit_system)}",
        f"- **Humidity:** {weather.get('relativeHumidity', '—')}%",
        f"- **Wind:** {_wind_speed(weather.get('windSpeed'), unit_system)} "
        f"from {_weather_compass(weather.get('windDirectionCompassPoint'))} "
        f"({wind_dir_label})",
    ]
    gust = weather.get("windGust")
    if gust:
        lines.append(f"- **Wind gust:** {_wind_speed(gust, unit_system)}")
    return lines


def format_elevation_block(act: dict[str, Any]) -> list[str]:
    gain = act.get("elevationGain")
    loss = act.get("elevationLoss")
    if gain is None and loss is None:
        return ["_No elevation summary on activity._"]

    lines = []
    if gain is not None:
        lines.append(f"- **Elevation gain:** {gain:.0f} m")
    if loss is not None:
        lines.append(f"- **Elevation loss:** {loss:.0f} m")
    min_e = act.get("minElevation")
    max_e = act.get("maxElevation")
    if min_e is not None and max_e is not None:
        lines.append(f"- **Min / max elevation:** {min_e:.0f} m / {max_e:.0f} m")
    return lines


def format_splits_table(splits: dict[str, Any] | None) -> list[str]:
    laps = (splits or {}).get("lapDTOs") or []
    if not laps:
        return ["_No lap splits available._"]

    header = (
        "| Split | Dist (km) | Time | Pace (km) | Pace (mi) | Elev+ (m) | Avg HR |"
    )
    sep = "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"
    rows = [header, sep]
    for lap in laps:
        idx = lap.get("lapIndex", "?")
        dist_m = float(lap.get("distance") or 0)
        duration = float(lap.get("duration") or 0)
        dist_km = dist_m / 1000.0
        rows.append(
            "| "
            + " | ".join(
                [
                    str(idx),
                    f"{dist_km:.2f}",
                    format_time(duration),
                    format_pace_per_km(duration, dist_m),
                    format_pace_per_mile(duration, dist_m),
                    f"{float(lap.get('elevationGain') or 0):.0f}",
                    str(int(lap.get("averageHR") or 0) or "—"),
                ]
            )
            + " |"
        )
    return rows


def format_zone_table(zones: list[dict[str, Any]] | None, label: str) -> list[str]:
    if not zones:
        return [f"_No {label} zone data._"]

    total = sum(float(z.get("secsInZone") or 0) for z in zones)
    if total <= 0:
        return [f"_No time recorded in {label} zones._"]

    header = "| Zone | Low bpm | Time | % of activity |"
    sep = "| ---: | ---: | ---: | ---: |"
    rows = [header, sep]
    for z in zones:
        secs = float(z.get("secsInZone") or 0)
        pct = (secs / total * 100) if total else 0
        rows.append(
            f"| {z.get('zoneNumber')} | {z.get('zoneLowBoundary')} | "
            f"{format_time(secs)} | {pct:.1f}% |"
        )
    return rows


def format_power_zone_table(zones: list[dict[str, Any]] | None) -> list[str]:
    if not zones:
        return ["_No power zone data._"]

    total = sum(float(z.get("secsInZone") or 0) for z in zones)
    if total <= 0:
        return ["_No power zone time recorded._"]

    header = "| Zone | Low (W) | Time | % of activity |"
    sep = "| ---: | ---: | ---: | ---: |"
    rows = [header, sep]
    for z in zones:
        secs = float(z.get("secsInZone") or 0)
        pct = (secs / total * 100) if total else 0
        rows.append(
            f"| {z.get('zoneNumber')} | {z.get('zoneLowBoundary')} | "
            f"{format_time(secs)} | {pct:.1f}% |"
        )
    return rows


def format_gear_block(gear: list[dict[str, Any]] | None) -> list[str]:
    if not gear:
        return ["_No gear linked to this activity._"]

    lines: list[str] = []
    for item in gear:
        gear_type = item.get("gearTypeName") or "Gear"
        name = item.get("customMakeModel") or item.get("displayName")
        if not name:
            make = item.get("gearMakeName") or ""
            model = item.get("gearModelName") or ""
            name = " ".join(p for p in (make, model) if p).strip() or "Unknown"
        lines.append(f"- **{gear_type}:** {name}")
    return lines


def build_agent_snapshot(
    act: dict[str, Any],
    enrichment: dict[str, Any],
    synced_at: str,
) -> dict[str, Any]:
    """Compact JSON-friendly snapshot for automated tooling."""
    weather = enrichment.get("weather") or {}
    wtype = weather.get("weatherTypeDTO") or {}
    return {
        "activity_id": act.get("activityId"),
        "name": act.get("activityName"),
        "start_local": act.get("startTimeLocal"),
        "activity_type": (act.get("activityType") or {}).get("typeKey"),
        "distance_km": round((act.get("distance") or 0) / 1000, 3),
        "duration_sec": act.get("duration"),
        "elevation_gain_m": act.get("elevationGain"),
        "elevation_loss_m": act.get("elevationLoss"),
        "avg_hr": act.get("averageHR"),
        "max_hr": act.get("maxHR"),
        "weather": {
            "conditions": wtype.get("desc"),
            "temp": weather.get("temp"),
            "apparent_temp": weather.get("apparentTemp"),
            "humidity_pct": weather.get("relativeHumidity"),
            "wind_speed": weather.get("windSpeed"),
            "wind_direction_deg": weather.get("windDirection"),
            "wind_compass": weather.get("windDirectionCompassPoint"),
        },
        "gear": [
            {
                "type": g.get("gearTypeName"),
                "name": g.get("customMakeModel") or g.get("displayName"),
            }
            for g in (enrichment.get("gear") or [])
        ],
        "synced_at": synced_at,
    }


def format_activity_section(
    act: dict[str, Any],
    enrichment: dict[str, Any],
    unit_system: str | None,
    synced_at: str | None = None,
) -> str:
    synced_at = synced_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    act_id = act.get("activityId")
    act_name = act.get("activityName", "Workout")
    start_time_str = act.get("startTimeLocal")
    distance = (act.get("distance") or 0) / 1000
    duration = act.get("duration", 0)
    avg_hr = act.get("averageHR")
    max_hr = act.get("maxHR")
    activity_type = (act.get("activityType") or {}).get("typeKey")

    lines = [
        f"# {act_name}",
        f"<!-- garmin-activity-id: {act_id} -->",
        f"<!-- garmin-activity-synced-at: {synced_at} -->",
        "",
        "### Summary",
        f"- **Date and time (local):** {start_time_str}",
        f"- **Activity ID:** {act_id}",
    ]
    if activity_type:
        lines.append(f"- **Type:** {activity_type}")
    lines.extend(
        [
            f"- **Distance:** {distance:.2f} km",
            f"- **Duration:** {format_time(duration)}",
        ]
    )
    if avg_hr:
        lines.append(f"- **Avg heart rate:** {avg_hr} bpm")
    if max_hr:
        lines.append(f"- **Max heart rate:** {max_hr} bpm")

    lines.extend(["", "### Weather", *format_weather_block(enrichment.get("weather"), unit_system)])
    lines.extend(["", "### Elevation", *format_elevation_block(act)])
    lines.extend(["", "### Kilometer splits", *format_splits_table(enrichment.get("splits"))])
    lines.extend(
        [
            "",
            "### Heart rate zones",
            *format_zone_table(enrichment.get("hr_zones"), "heart rate"),
        ]
    )
    lines.extend(
        [
            "",
            "### Power zones",
            *format_power_zone_table(enrichment.get("power_zones")),
        ]
    )
    lines.extend(["", "### Gear", *format_gear_block(enrichment.get("gear"))])

    snapshot = build_agent_snapshot(act, enrichment, synced_at)
    lines.extend(
        [
            "",
            "### Agent snapshot",
            "```json",
            json.dumps(snapshot, indent=2, ensure_ascii=False),
            "```",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def merge_session_notes(previous_content: str | None, new_content: str) -> str:
    """Keep user-edited session notes when refreshing an activity from Garmin."""
    if not previous_content or SESSION_NOTES_HEADING not in previous_content:
        return new_content

    old_notes = previous_content.split(SESSION_NOTES_HEADING, 1)[1].strip()
    if not old_notes or old_notes == SESSION_NOTES_PLACEHOLDER:
        return new_content

    return new_content.rstrip() + "\n\n" + SESSION_NOTES_HEADING + old_notes + "\n"
