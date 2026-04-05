# ShowNotes – Copilot Instructions

## Project Overview

Flask-based Plex companion app. Self-hosted TV/movie library explorer with spoiler-aware AI summaries, viewing history, character/actor relationship mapping, calendar views, and deep integration with Sonarr, Radarr, Tautulli, Bazarr, and Plex.

## Dev Commands

```bash
# Full setup
make setup          # venv, deps, DB init, .env
make dev            # Flask dev server on port 5003
make watch          # Dev server + Tailwind watcher (tmux)

# CSS (required when changing templates)
make watch-css      # Rebuilds on change
make build-css      # One-time build

# Database
python3 init_fresh_database.py   # Wipe and reinitialize
python3 app/migrations/XXX_migration_name.py  # Run specific migration

# Tests / Lint
make test           # pytest
make lint           # flake8 + black

# Docker
make docker-build
make docker-run
make docker-stop
```

**Single test:**
```bash
source venv/bin/activate && pytest tests/test_<module>.py::test_<name> -v
```

**Tailwind is required for UI changes** — templates use Tailwind utility classes; without the watcher, changes won't appear. Source: `app/static/input.css` → compiled to `app/static/css/style.css`.

## Architecture

Flask app factory pattern (`create_app()` in `app/__init__.py`) with two blueprints:

| Blueprint | Prefix | File |
|-----------|--------|------|
| User-facing | `/` | `app/routes/main.py` (~8600 LOC) |
| Admin panel | `/admin/` | `app/routes/admin.py` |

**No ORM** — all DB access uses raw `sqlite3` with `Row` factory and `?` parameter binding.

| Module | Responsibility |
|--------|---------------|
| `app/database.py` | Connection management, `init_db()`, schema versioning |
| `app/utils.py` | All external service integration (~2600 LOC) |
| `app/episode_data_services.py` | Episode data management |
| `app/scheduler.py` | APScheduler background sync tasks |
| `app/system_logger.py` | Application logging |
| `app/cli.py` | Flask CLI commands (image queue processing) |

**Webhook endpoints:**
- Plex → `/plex-webhook` (play/pause/resume/stop/scrobble)
- Sonarr → admin blueprint (series add/delete, episode downloads)
- Radarr → admin blueprint (movie library changes)

Webhooks drive automatic DB sync; no polling needed for library changes.

**Image caching:** All external images (posters, backgrounds, cast) are proxied through `image_cache_queue` and served from `static/poster/`, `static/background/`, `static/cast/`. Never use direct external image URLs in templates — always go through the cache system. Use `onerror` fallback to placeholder.

**Settings:** Two-tier config — `.env` for bootstrap values (service URLs, API keys), `settings` DB table for runtime config (Plex OAuth, sync schedules, LLM config). `app/__init__.py` loads both.

## Key Conventions

**Database migrations:**
1. Create `app/migrations/NNN_description.py` (next sequential number)
2. Implement `upgrade()` function
3. Use `IF NOT EXISTS` on `CREATE TABLE`, handle `ALTER TABLE` failures gracefully
4. Fresh installs use `init_db()` (consolidated schema) — migrations are for existing installs only
5. Archived migrations live in `app/migrations_archive/`

**Route handlers should be thin** — business logic belongs in `utils.py` or dedicated service modules, not in blueprint files.

**Service integration pattern** (adding a new service):
1. Migration to add URL/key fields to `settings` table
2. `test_[service]_connection()` function in `utils.py`
3. Sync functions in `utils.py`
4. Admin UI in `admin_settings.html` with test button
5. Endpoints in `app/routes/admin.py`

**Naming:**
- Service ID columns: `sonarr_id`, `radarr_id`, `tmdb_id`, `tvdb_id`
- Cache invalidation column: `last_synced_at`
- Plex event types: `play`, `pause`, `resume`, `stop`, `scrobble`

**UI standards:**
- Tailwind CSS dark mode throughout — all new UI must support dark mode
- Mobile-responsive required
- Season 0 ("Specials") is hidden from episode lists
- DEV/PROD environment badge shown in footer (controlled by `ENVIRONMENT` env var)

## Environment

See `.env.example`. Key variables:
```env
ENVIRONMENT=development    # or production
SECRET_KEY=                # Change in production
SONARR_URL / SONARR_API_KEY
RADARR_URL / RADARR_API_KEY
TAUTULLI_URL / TAUTULLI_API_KEY
BAZARR_URL / BAZARR_API_KEY
PLEX_CLIENT_ID=shownotes-yourname
OLLAMA_URL
OPENAI_API_KEY             # Optional
```

## Deployment

```
/home/scott/projects/show_notes_dev   ← dev repo (git)
/home/docker/compose/shownotes/       ← production compose + .env
/home/docker/appdata/shownotes/       ← DB, logs, image cache
```

`deploy.sh` syncs compose files, runs migrations, and manages container lifecycle.

## Open Brain (Persistent Memory)

Open Brain is the shared knowledge base across all AI sessions. **Query it before answering questions about past decisions, homelab state, or anything from previous sessions.**

- **MCP server:** `https://rqauqdlngxxxeqouuigo.supabase.co/functions/v1/open-brain-mcp`
- **Key:** stored in `~/.copilot/mcp-config.json`

| Trigger | Action |
|---------|--------|
| "remember this…" | Call `capture_thought` immediately |
| Questions about past decisions, goals, server details | Call `search_thoughts` first |
| "what did I capture / what do I know about X" | Call `search_thoughts` |
| "what was I working on / what's next" | Call `list_thoughts` or `search_thoughts` |

Never say "I don't have memory of that" — search Open Brain first.

## Homelab Context

- **When diagnosing issues**, check the documentation vault first: `/mnt/media-chitek/Homelab/Documentation/`
- **After resolving an issue or completing a setup task**, document it in the vault:
  - New service setup → `Homelab/Docker/Services/`
  - Bug fix / incident → `Homelab/Fixes & Incidents/`
- **Docker skills** and compose templates: `/home/docker/compose/` and `~/homelab-claude/skills/docker.md`
- Homepage dashboard skill: `~/homelab-claude/skills/homepage.md`
