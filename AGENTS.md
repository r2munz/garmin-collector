# Agent guide

Instructions for humans and coding agents working in **garmin-collector**.

## What this project does

Syncs Garmin Connect activities via the [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) library into **one Markdown file per activity** under `YYYY/MM/YYYY-MM-DD_HH-MM-SS_{type}.md` (local start time; activity ID only in file metadata), with enriched sections (weather, elevation, splits, zones, gear). Cloud edits replace the file; user **session notes** are kept when present (empty placeholder is omitted). Sync uses a date range: first run (no monthly files yet) defaults to **Jan 1 of the current year → today**; later runs default to the **last 7 days**. Session tokens are cached on disk when possible.

## Repository layout

| Path | Purpose |
|------|---------|
| `src/garmin_collector/main.py` | Entry point: login, fetch activities, write `.md` files |
| `src/garmin_collector/openwebui_sync.py` | Optional push of monthly `.md` to Open WebUI Knowledge |
| `src/garmin_collector/paths.py` | Output paths (`OUTPUT_DIR`, knowledge-id / KB folder layout) |
| `pyproject.toml` / `pdm.lock` | Dependencies and PDM scripts (Python **3.11** only) |
| `.env.example` | Template for local env vars (copy to `.env`, never commit `.env`) |
| `Dockerfile` / `docker-compose.yml` | Containerized one-shot sync (`/data`, `/tokens` volumes) |

Unit tests live under `tests/`; run `pdm run test`. Prefer extending tests when changing `format_activity`, `activity_store`, `openwebui_sync`, or sync-window logic.

## Commands

Use **PDM** for all Python work (in-project venv at `.venv/`):

```bash
pdm install              # sync deps from lockfile
pdm run collect          # run the collector (see env vars below)
pdm add <package>        # new dependency; commit pyproject.toml + pdm.lock
```

Docker:

```bash
docker compose up --build
```

**First sync vs incremental (Docker):** mount an empty `/data` volume once → year-to-date; later runs with the same compose file → last 7 days. See `README.md` § Docker.

After changing dependencies, run `pdm lock` / `pdm install` locally and ensure `docker build` still succeeds.

## Environment variables

| Variable | Required | Default | Notes |
|----------|----------|---------|--------|
| `GARMIN_EMAIL` | yes | — | Garmin account email |
| `GARMIN_PASSWORD` | yes | — | Garmin account password |
| `OUTPUT_DIR` | no | `/data` | Activity Markdown tree (`YYYY/MM/YYYY-MM-DD_HH-MM-SS_{type}.md`) |
| `TOKEN_DIR` | no | `/tokens` | Persisted `garth` session tokens |
| `SYNC_START` / `SYNC_END` | no | — | Inclusive window (`YYYY-MM-DD`); overrides lookback / first-sync defaults |
| `SYNC_LOOKBACK_DAYS` | no | `7` | Incremental window when monthly files already exist; default set in `docker-compose.yml` for Docker |
| `OPENWEBUI_BASE_URL` / `OPENWEBUI_API_KEY` / `OPENWEBUI_KNOWLEDGE_ID` | no | — | After collect, sync `activities_*.md` to Open WebUI Knowledge (`openwebui_sync.py`) |
| `OPENWEBUI_KB_FOLDER` | no | — | KB subdirectory (e.g. `Activities`); manifest path `Folder/file.md` |
| `OPENWEBUI_SYNC_ENABLED` | no | on when URL+key+ID set | Set `false` to disable vector push |
| `OPENWEBUI_SYNC_ALL` | no | `false` | One-time backfill: upload every month Open WebUI diff wants |
| `OPENWEBUI_SYNC_CLEANUP` | no | `false` | Mirror-delete remote files not in manifest (avoid on mixed KBs) |

Local dev: use `./data` and `./tokens` (see `.env.example`). `load_dotenv()` runs at import time in `main.py`.

**Never** commit credentials, `.env`, token directories (`tokens/`, `garmin_tokens/`), or scraped `data/`.

## Conventions

- **Language:** User-facing strings, docstrings, and docs are **English**.
- **Style:** Match existing code in `main.py` (type hints, straightforward control flow). Avoid large refactors unless asked.
- **Scope:** This is an application (`[tool.pdm] distribution = false`), not a published package. Code lives under `src/garmin_collector/`; `PYTHONPATH=src` is set for `pdm run collect` and the Docker image.
- **Git:** Do not create commits or PRs unless the user explicitly asks.
- **Secrets in compose:** `docker-compose.yml` may contain placeholders; prefer env files or secrets for real deployments.

## Safe extension ideas

When adding features, typical next steps (confirm with the user first):

- Richer Markdown (laps, splits, HR zones) via additional `Garmin` API calls.
- Re-sync refreshes each activity block by ID (manual session notes are preserved).
- Scheduled runs via external cron or compose `restart` policy—not an in-container scheduler unless requested.

## Garmin / API caveats

- Login can fail if tokens expire or Garmin changes auth; token refresh path is `garmin.login(TOKEN_DIR)` with fallback to password login and `garmin.garth.dump(TOKEN_DIR)`.
- Network access is required for sync; agents should not assume offline tests pass without mocking.

## Where to look

- Human-oriented setup: `README.md`
- Behavior and output format: `src/garmin_collector/main.py`
- Container paths and volumes: `docker-compose.yml`
