# garmin-collector

Collects Garmin user data and stores it.

Contributors and coding agents: see [AGENTS.md](AGENTS.md).

## Setup

Requires [PDM](https://pdm-project.org/) and Python 3.11.

Create the in-project virtualenv and install dependencies:

```bash
pdm install
```

PDM uses `.venv/` in this repo (see `venv.in_project` in `pyproject.toml`). The active interpreter is recorded in `.pdm-python`.

Copy environment variables for local runs:

```bash
cp .env.example .env
# edit .env with your Garmin credentials
```

## Run

`pdm run collect` loads variables from `.env` in the project root (see `.env.example`). Activities are appended to monthly files under `OUTPUT_DIR` (`activities_YYYY-MM.md`). The first run syncs from 1 January of the current year; later runs use the last 7 days unless you set `SYNC_START` / `SYNC_END`.

```bash
pdm run collect
```

### Using the environment day to day

| Goal | Command |
|------|---------|
| Run the collector | `pdm run collect` |
| Run unit tests | `pdm run test` |
| Run any Python with project deps | `pdm run python …` |
| Interactive shell with venv active | `pdm shell` |
| Activate venv manually | `source .venv/bin/activate` |

In Cursor/VS Code, choose the interpreter: `.venv/bin/python`.

## Docker

### Prerequisites

1. Copy and edit credentials: `cp .env.example .env` (only `GARMIN_EMAIL` and `GARMIN_PASSWORD` are required for Compose).
2. In `docker-compose.yml`, set the host path for your knowledge-base output (left side of the `/data` volume).
3. Build and run:

```bash
docker compose up --build
```

Compose loads `.env` for credentials, sets container paths and **sync defaults** in `docker-compose.yml` (`OUTPUT_DIR`, `TOKEN_DIR`, `SYNC_LOOKBACK_DAYS`, optional `SYNC_START` / `SYNC_END`), and persists Garmin session tokens in `./garmin_tokens` on the host.

### First sync (year to date) then incremental (last 7 days)

The collector picks the date window automatically from what is already on disk. Default lookback is **`SYNC_LOOKBACK_DAYS=7`** in `docker-compose.yml` (override via host `.env` if needed).

| Situation | What happens |
|-----------|----------------|
| **First run** | No `activities_YYYY-MM.md` files under the mounted `/data` directory → sync **1 January of the current calendar year** through today (inclusive). |
| **Every later run** | At least one monthly file exists → sync only the **last 7 days** (`SYNC_LOOKBACK_DAYS`, default `7`) through today. Activities are **upserted** by ID in the monthly files (cloud edits refresh stored blocks). |

**Recommended flow**

1. **Prepare an empty data directory** on the host (or a new folder you mount to `/data`) so no `activities_*.md` files exist yet.
2. **First sync** — pull the year so far:

   ```bash
   docker compose up --build
   ```

   Wait until the container exits. Check the host path you mounted: you should see files like `activities_2025-01.md`, `activities_2025-02.md`, …

3. **Ongoing syncs** — use the **same command** on a schedule (cron, systemd timer, Watchtower, etc.):

   ```bash
   docker compose run --rm garmin-collector
   ```

   Each run only queries Garmin for the last seven days and upserts activities in the monthly Markdown files. Leave `SYNC_START` / `SYNC_END` empty in `docker-compose.yml` (default) for automatic first-sync / lookback behavior.

Example cron (daily at 06:00, from the project directory):

```cron
0 6 * * * cd /path/to/garmin-collector && docker compose run --rm garmin-collector >> /var/log/garmin-collector.log 2>&1
```

### Overrides (optional)

Edit `docker-compose.yml` defaults or set the same variables in host `.env` (Compose substitution picks them up):

- `SYNC_LOOKBACK_DAYS=14` — wider incremental window after the first sync.
- `SYNC_START=2025-01-01` and `SYNC_END=2025-10-21` — fixed range; ignores first-sync / lookback logic.

To **repeat a full year-to-date pull** without wiping the store, set `SYNC_START` / `SYNC_END` for one run; existing activity IDs are refreshed in place. To rebuild from scratch, remove `activities_*.md` from the host data directory and run again (first-sync behavior).
