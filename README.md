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

`pdm run collect` loads variables from `.env` in the project root (see `.env.example`). Each activity is written to **`YYYY/MM/{type}_{activityId}.md`** under `OUTPUT_DIR` (one file per workout, RAG-friendly). The first run syncs from 1 January of the current year; later runs use the last 7 days unless you set `SYNC_START` / `SYNC_END`.

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

## Open WebUI (optional vector / RAG sync)

After each successful `pdm run collect`, you can push activity Markdown files into an [Open WebUI](https://github.com/open-webui/open-webui) **Knowledge** base. The collector calls Open WebUI’s HTTP API (`sync/diff` → upload changed files → embed into the configured vector DB). Requires **Open WebUI ≥ 0.9.6** for incremental sync.

1. In Open WebUI: create a Knowledge base and copy its ID; create an API key under **Settings → Account**.
2. Set in `.env` (see `.env.example`):

   - `OPENWEBUI_BASE_URL` — e.g. `http://localhost:3000`
   - `OPENWEBUI_API_KEY`
   - `OPENWEBUI_KNOWLEDGE_ID`
   - `OPENWEBUI_SYNC_ENABLED=true` (optional; enabled automatically when all three are set)

3. Run `pdm run collect` as usual. By default only **activity files written in that run** are uploaded to Open WebUI (matches incremental Garmin lookback). Set **`OPENWEBUI_SYNC_ALL=true`** once to backfill every local file the server diff marks as out of date.

With `OPENWEBUI_KNOWLEDGE_ID` set, files are stored under **`OUTPUT_DIR/<OPENWEBUI_KNOWLEDGE_ID>/`** by default (`OPENWEBUI_KB_SUBDIR=true`). Use **`OPENWEBUI_KB_FOLDER`** (e.g. `Activities`) to match a folder inside that knowledge base; manifest paths look like `Activities/2026/10/running_12345678.md`. Set `OPENWEBUI_KB_SUBDIR=false` to skip the knowledge-id segment on disk.

**Quick test** (narrow Garmin window, then vector push):

```bash
SYNC_START=2026-01-01 SYNC_END=2026-01-07 pdm run collect
ls -la "./data/$OPENWEBUI_KNOWLEDGE_ID/"
```

If Open WebUI sync fails, Garmin export still completes; the error is logged at the end of the run.

## Docker

### Prerequisites

1. Copy and edit credentials: `cp .env.example .env` (only `GARMIN_EMAIL` and `GARMIN_PASSWORD` are required for Compose).
2. Activity files are stored on the **`garmin_data` Docker volume** at `/data` inside the container (`YYYY/MM/{type}_{id}.md`). To use a host folder instead, replace `garmin_data:/data` with a bind mount in `docker-compose.yml`.
3. Build and run:

```bash
docker compose up --build
```

Compose loads `.env` for credentials, sets container paths and **sync defaults** in `docker-compose.yml` (`OUTPUT_DIR`, `TOKEN_DIR`, `SYNC_LOOKBACK_DAYS`, optional `SYNC_START` / `SYNC_END`), and persists data on named volumes `garmin_data` (Markdown KB) and `garmin_tokens` (login).

### First sync (year to date) then incremental (last 7 days)

The collector picks the date window automatically from what is already on disk. Default lookback is **`SYNC_LOOKBACK_DAYS=7`** in `docker-compose.yml` (override via host `.env` if needed).

| Situation | What happens |
|-----------|----------------|
| **First run** | No activity Markdown under the store path → sync **1 January of the current calendar year** through today (inclusive). |
| **Every later run** | At least one activity file exists (or legacy `activities_*.md` at store root) → sync only the **last 7 days** (`SYNC_LOOKBACK_DAYS`, default `7`) through today. Each activity is **upserted** by ID into its own file. |

**Recommended flow**

1. **Prepare an empty data directory** on the host (or a new folder you mount to `/data`) so no prior activity store exists yet.
2. **First sync** — pull the year so far:

   ```bash
   docker compose up --build
   ```

   Wait until the container exits. Check the store path: you should see folders like `2026/01/`, `2026/02/`, each with per-activity `.md` files.

3. **Ongoing syncs** — use the **same command** on a schedule (cron, systemd timer, Watchtower, etc.):

   ```bash
   docker compose run --rm garmin-collector
   ```

   Each run only queries Garmin for the last seven days and upserts per-activity Markdown files. Leave `SYNC_START` / `SYNC_END` empty in `docker-compose.yml` (default) for automatic first-sync / lookback behavior.

Example **hourly** cron (set `SYNC_LOOKBACK_DAYS=2` in `.env` for a narrow Garmin window):

```cron
0 * * * * cd /path/to/garmin-collector && docker compose run --rm garmin-collector >> /var/log/garmin-collector.log 2>&1
```

### Overrides (optional)

Edit `docker-compose.yml` defaults or set the same variables in host `.env` (Compose substitution picks them up):

- `SYNC_LOOKBACK_DAYS=2` — narrower incremental window (e.g. hourly schedule).
- `SYNC_LOOKBACK_DAYS=14` — wider incremental window after the first sync.
- `SYNC_START=2025-01-01` and `SYNC_END=2025-10-21` — fixed range; ignores first-sync / lookback logic.

To **repeat a full year-to-date pull** without wiping the store, set `SYNC_START` / `SYNC_END` for one run; existing activity IDs are refreshed in place. To rebuild from scratch, remove the activity tree (and any legacy `activities_*.md` files) from the store directory and run again (first-sync behavior).
