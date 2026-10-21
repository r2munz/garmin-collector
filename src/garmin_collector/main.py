import os
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv
from garminconnect import Garmin

from garmin_collector.enrichment import fetch_activity_enrichment
from garmin_collector.format_activity import format_activity_section
from garmin_collector.monthly_store import (
    activity_month_key,
    has_existing_monthly_store,
    monthly_file_path,
    upsert_activity_section,
)
from garmin_collector.openwebui_sync import maybe_sync_to_openwebui
from garmin_collector.paths import resolve_output_dir

load_dotenv()

EMAIL = os.getenv("GARMIN_EMAIL")
PASSWORD = os.getenv("GARMIN_PASSWORD")
TOKEN_DIR = os.getenv("TOKEN_DIR", "/tokens")


def init_garmin() -> Garmin:
    """Initialize the API, loading or persisting the session token."""
    garmin = Garmin(EMAIL, PASSWORD)

    os.makedirs(TOKEN_DIR, exist_ok=True)

    try:
        print("Attempting login with existing token...")
        garmin.login(TOKEN_DIR)
    except Exception:
        print("Token missing or invalid. Logging in with credentials...")
        garmin.login()
        garmin.garth.dump(TOKEN_DIR)
        print("New token saved successfully.")

    return garmin


def parse_iso_date(value: str | None) -> date | None:
    """Parse YYYY-MM-DD from env or None."""
    if not value or not value.strip():
        return None
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def start_of_current_year(today: date) -> date:
    return date(today.year, 1, 1)


def resolve_sync_window(output_dir: str, today: date | None = None) -> tuple[date, date]:
    """Choose inclusive sync range from env or defaults (first sync vs incremental)."""
    today = today or date.today()
    end = parse_iso_date(os.getenv("SYNC_END")) or today
    start_override = parse_iso_date(os.getenv("SYNC_START"))

    if start_override:
        if start_override > end:
            raise ValueError(f"SYNC_START ({start_override}) must be on or before SYNC_END ({end})")
        print(f"Sync window (from env): {start_override} through {end}")
        return start_override, end

    if not has_existing_monthly_store(output_dir):
        start = start_of_current_year(today)
        print(f"First sync (no monthly store): {start} through {end}")
        return start, end

    lookback_days = int(os.getenv("SYNC_LOOKBACK_DAYS", "7"))
    start = end - timedelta(days=lookback_days)
    print(f"Incremental sync (last {lookback_days} days): {start} through {end}")
    return start, end


def fetch_activities_in_range(client: Garmin, start: date, end: date) -> list[dict]:
    """Load all activities with start dates in [start, end] (inclusive)."""
    return client.get_activities_by_date(
        start.isoformat(),
        end.isoformat(),
        sortorder="asc",
    )


def sync_activity(
    client: Garmin,
    output_dir: str,
    act: dict,
    unit_system: str | None,
) -> str | None:
    """Fetch enriched data and upsert one activity. Returns store action or None if skipped."""
    act_id = act.get("activityId")
    if act_id is None:
        print("Skipping activity without activityId")
        return None

    act_id_str = str(act_id)
    month_key = activity_month_key(act.get("startTimeLocal"))
    if not month_key:
        print(f"Skipping activity {act_id_str}: missing or invalid startTimeLocal")
        return None

    synced_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    enrichment = fetch_activity_enrichment(client, act_id_str)
    section = format_activity_section(act, enrichment, unit_system, synced_at=synced_at)
    return upsert_activity_section(output_dir, month_key, act_id_str, section)


def main() -> None:
    if not EMAIL or not PASSWORD:
        print("Error: GARMIN_EMAIL and GARMIN_PASSWORD environment variables are required.")
        return

    output_dir = resolve_output_dir()
    os.makedirs(output_dir, exist_ok=True)
    if output_dir != (os.getenv("OUTPUT_DIR") or "/data"):
        print(f"Using knowledge-scoped output directory: {output_dir}")

    client = init_garmin()
    unit_system = client.get_unit_system()

    try:
        start, end = resolve_sync_window(output_dir)
    except ValueError as exc:
        print(f"Error: {exc}")
        return

    print("Fetching activities in range...")
    activities = fetch_activities_in_range(client, start, end)
    print(f"Received {len(activities)} activities from Garmin.")

    created = 0
    updated = 0
    skipped = 0
    touched_monthly_files: set[str] = set()
    for act in activities:
        result = sync_activity(client, output_dir, act, unit_system)
        if result == "created":
            created += 1
        elif result == "updated":
            updated += 1
        else:
            skipped += 1
        if result in ("created", "updated"):
            month_key = activity_month_key(act.get("startTimeLocal"))
            if month_key:
                touched_monthly_files.add(os.path.basename(monthly_file_path(output_dir, month_key)))

    print(f"Done. Created {created}, updated {updated}, skipped {skipped}.")

    try:
        maybe_sync_to_openwebui(output_dir, touched_filenames=touched_monthly_files)
    except Exception as exc:
        print(f"Open WebUI sync failed: {exc}")


if __name__ == "__main__":
    main()
