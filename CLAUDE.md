# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ShowNotes is a Flask-based web application that serves as a Plex television companion. It helps users explore TV shows, character arcs, and actor overlap between series with spoiler-aware summaries, relationship mapping, and chat-style interaction. The app integrates with Sonarr, Radarr, Bazarr, Tautulli, Ollama/OpenAI, and Plex to provide comprehensive TV show metadata and viewing history tracking.

## Development Commands

### Running the Application

```bash
# Start the Flask development server (port 5001)
python3 run.py

# Or using the venv explicitly
.venv/bin/python run.py
```

### CSS/Styling with Tailwind

The application uses Tailwind CSS. When making UI changes, you must run the Tailwind watcher:

```bash
# Watch Tailwind CSS changes
./watch_tailwind.sh

# Or manually
npx tailwindcss -i ./app/static/src/input.css -o ./app/static/css/style.css --watch
```

### Database Management

The application uses SQLite with a migration-based system:

```bash
# Database is located at: instance/shownotes.sqlite3

# Run a specific migration
python3 app/migrations/XXX_migration_name.py

# Or use the migration runner for newer migrations
python3 run_migration_024.py

# Initialize database from scratch (destructive!)
FLASK_APP=run.py flask init-db
```

**Important**: The database uses numbered migrations (000-024+) in `app/migrations/`. Always create new migrations following the existing pattern.

### Image Processing

Images are cached locally in the static directory:

```bash
# Process queued images
flask image process-queue --limit 10 --delay 2
```

## Architecture Overview

### Application Structure

- **Flask App Factory Pattern**: `create_app()` in `app/__init__.py` initializes the app, registers blueprints, and configures Flask-Login
- **Blueprint-Based Routes**:
  - `app/routes/main.py`: User-facing routes (homepage, show details, character pages)
  - `app/routes/admin.py`: Admin panel routes (settings, tasks, logs) under `/admin/` prefix
- **No ORM**: Direct SQLite queries via `sqlite3` module with `Row` factory

### Key Modules

- `app/database.py`: Database connection management, initialization, and schema versioning
- `app/utils.py`: Core service integration functions (Sonarr, Radarr, Bazarr, Tautulli, Pushover), connection testing, data synchronization, and image handling
- `app/episode_data_services.py`: Episode-specific data management
- `app/cli.py`: Flask CLI commands (image processing queue)

### Database Schema

Key tables:
- `users`: User accounts with Plex authentication support
- `settings`: Application-wide configuration (service URLs, API keys)
- `sonarr_shows`, `sonarr_seasons`, `sonarr_episodes`: TV show metadata from Sonarr
- `radarr_movies`: Movie metadata from Radarr
- `plex_activity_log`: Detailed Plex webhook events (play, pause, resume, stop, scrobble)
- `api_usage`: LLM API call tracking for cost monitoring
- `image_cache_queue`: Background image caching queue
- `user_favorites`, `user_watch_history`: User profile features for tracking favorites and watch history

The schema is managed via numbered migration files in `app/migrations/`.

### External Service Integration

The app integrates with multiple external services:

1. **Sonarr**: TV show library, episode metadata, webhooks for automatic syncing
2. **Radarr**: Movie library, metadata, webhooks
3. **Plex**: User authentication (OAuth), viewing history via webhooks
4. **Tautulli**: Watch history synchronization
5. **Bazarr**: Subtitle import for search
6. **Pushover**: Admin notifications for issue reports

### Webhook System

The application receives webhooks from:
- **Plex**: Tracks viewing activity (play/pause/resume/stop/scrobble) to route `/plex-webhook`
- **Sonarr**: Auto-syncs library changes (series add/delete, episode downloads) to route in admin blueprint
- **Radarr**: Auto-syncs movie library changes to route in admin blueprint

Webhooks trigger background sync operations to keep the local database current without manual intervention.

### Authentication

- Uses Flask-Login for session management
- Supports Plex OAuth (PIN-based flow) for user authentication
- Admin users have elevated privileges (database flag `is_admin`)
- Sessions persist for 30 days

## Important Patterns and Conventions

### Image Handling

- Images are served from local static cache: `/static/poster/[tmdb_id].jpg` and `/static/background/[tmdb_id].jpg`
- Images use `onerror` attributes pointing to generic placeholder images
- Image URLs from external services are proxied and cached via the `image_cache_queue` system
- Never construct direct external image URLs in templates; use the caching proxy


### Error Handling and Logging

- Use `current_app.logger` for logging within request context
- Service connection failures should be graceful with clear error messages
- Connection test functions in `utils.py` follow pattern: `test_[service]_connection()`

### Database Migrations

When modifying the database schema:
1. Create a new numbered migration file in `app/migrations/`
2. Follow the existing pattern with `upgrade()` function
3. Use `IF NOT EXISTS` for CREATE TABLE, handle ALTER TABLE failures gracefully
4. Test migrations on a copy of the database before applying
5. Update `database.py` if the main schema initialization needs changes

### UI/UX Standards

- Dark mode is fully supported via Tailwind CSS
- All service logos should support both light and dark mode
- Use collapsible sections for admin settings pages
- Mobile-responsive design is required
- Season 0 ("Specials") is hidden from episode lists
- Episodes should show "Available" label when file exists

### Code Style

- Use descriptive docstrings for functions, especially in `utils.py` and `llm_services.py`
- Keep route handlers in blueprint files thin; move logic to `utils.py` or service modules
- Database queries should use parameter binding (?) to prevent SQL injection
- Validate external API responses before using data

## Common Tasks

### Adding a new external service integration

1. Add URL and API key fields to `settings` table via migration
2. Add connection test function in `utils.py` following `_test_service_connection()` pattern
3. Create sync functions in `utils.py`
4. Add admin UI controls in `app/templates/admin_settings.html`
5. Update `app/routes/admin.py` for test and sync endpoints


### Testing service connections

All service connections can be tested via the admin panel at `/admin/settings`. Each service has a "Test" button that triggers an API connection test and displays real-time status.

## Configuration

- Environment variables loaded from `.env` file (see `.env.example`)
- Application settings stored in `settings` table (database-driven configuration)
- Plex OAuth credentials stored securely in database (not in environment)
- Default Flask port: 5003
- Default session lifetime: 30 days

## Production Deployment

### Docker Deployment (Recommended)

The recommended production deployment uses Docker with the following structure:

```bash
# Directory structure
/home/docker/appdata/shownotes/    # App data (database, logs, static files)
/home/docker/compose/shownotes/    # Docker compose files and .env
/home/scott/projects/show_notes_dev # Development directory (git repo)
```

**Setup Steps:**

1. **Create required directories:**
   ```bash
   mkdir -p /home/docker/appdata/shownotes/{logs,static}
   mkdir -p /home/docker/compose/shownotes
   ```

2. **Copy compose files to production directory:**
   ```bash
   cp docker-compose.yml /home/docker/compose/shownotes/
   cp .env.example /home/docker/compose/shownotes/.env
   ```

3. **Configure environment:**
   ```bash
   cd /home/docker/compose/shownotes
   nano .env  # Edit: Set ENVIRONMENT=production, SECRET_KEY, etc.
   ```

4. **Build and start:**
   ```bash
   docker-compose up -d
   ```

5. **View logs:**
   ```bash
   docker-compose logs -f
   ```

**Environment Badge:**
The footer displays a "DEV" (yellow) or "PROD" (green) badge based on the `ENVIRONMENT` variable to help distinguish between development and production instances.

### Traditional Deployment

- Change `SECRET_KEY` in `app/__init__.py` or via environment variable
- Set `ENVIRONMENT=production` in `.env`
- Set `SESSION_COOKIE_SECURE=True` when running with HTTPS
- The app includes a `shownotes.service` systemd service file for automatic restart
- Advanced development setup with systemd, tmux, and watchdog available (see `docs/dev-server-watchdog.md`)

## Recent Changes

- **Database Schema Consolidation**: All migrations have been consolidated into `init_db()` for clean, single-step fresh installations. Migrations are archived in `app/migrations_archive/` for reference. Fresh installations get the complete schema automatically without needing to run migrations.
- **Docker Deployment**: Added Dockerfile and docker-compose.yml for production deployment with proper volume mappings for data persistence
- **Environment Badges**: Footer now displays "DEV" or "PROD" badge based on `ENVIRONMENT` variable to distinguish between development and production instances
- **LLM Features Removed**: Character summary and chat features using LLMs (Ollama/OpenAI) have been completely removed. Character detail pages now focus on actor information and cross-show appearances
- **User Profile Features**: User favorites, watch history, statistics, and notification preferences are now included in the initial schema
- **Removed Components**: Recap scrapers (`recap_scrapers.py`), Wikipedia scraper (`wikipedia_scraper.py`), LLM-powered character summaries, and multiple admin prompt management pages have been removed
- **Streamlined Admin**: Admin panel has been simplified, removing redundant API usage logs and prompt viewing pages
