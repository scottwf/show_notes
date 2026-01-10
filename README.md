# ShowNotes
Your plex television companion
## Overview

ShowNotes is a Flask-based web app that helps users explore TV shows, character arcs, and actor overlap between series. It offers spoiler-aware summaries, relationship mapping, chat-style interaction, and integration with metadata sources like local installations of Radarr, Sonarr, Bazarr, Tautulli and Ollama.

The purpose of ShowNotes is to be a tool for exploring tv show, season and character summaries, overlap detection, actor insights, and spoiler-aware recaps based on viewing progress. Using a plex webhook the plex users' viewing is imported and stored in a sqlite3 database for each user. Using Jellyseer as inspiration for layout and visual deesign to be usable on a phone and computer. Also use plex autentication to sign in for an administrator and users. 

---

## 🆕 Recent Improvements

### **December 2025 - UI/UX & Character System Enhancements**
- **Next Episode Display:** Restored the "Next Episode" functionality on show detail pages, displaying upcoming episodes with air dates for actively airing shows with clean, readable styling in both light and dark modes.
- **Character Detail System:** Fixed character page routing and database queries, transitioning from `actor_id` to `character_id` (primary key) for accurate character identification and resolved "Character not found" errors.
- **LLM Character Summaries:** Enhanced character summary accuracy by adding comprehensive context (show overview, episode details, actor names, other characters) to LLM prompts, reducing hallucinations and improving character-specific responses.
- **LLM Testing Tools:** Added cache clearing functionality and refresh buttons for character pages to facilitate prompt testing and iteration without database interference.
- **Show Detail Page Readability:** Fixed transparency issues in both light and dark modes, ensuring all text is clearly readable against background images with optimized opacity levels (98% for light mode, 95% for dark mode).
- **Sonarr Metadata Sync:** Implemented targeted episode updates via Sonarr webhooks for improved metadata freshness without full library syncs.

### **Previous Improvements**
- **Search Highlighting:** Implemented keyboard navigation highlighting for search results, matching the mouse hover style.
- **Image Loading:** Updated image loading strategy to use locally cached images (posters and backgrounds) served from `/static/poster/` and `/static/background/` respectively, with filenames based on TMDB IDs. Image queuing for Sonarr and Radarr syncs now prepares files for this local cache.
- **Show Detail Page:** Significantly enhanced the Show Detail page with a new Sonarr-like layout including a background image, detailed metadata (first air date, status, next episode, IMDb link), collapsible season/episode lists, and display of the 'currently watched' episode based on Plex activity.
- **Homepage Layout:** Revamped the homepage to prominently display the 'currently playing/paused' item and a grid of 'previously watched' items, derived from Plex activity.
- **Tautulli Integration:** Completed support for syncing watch history from Tautulli with connection testing.
- **Episode Pages:** Episodes are now clickable from show details and the homepage.
- **Collapsible Service Cards:** All service settings on the admin page start collapsed for easier navigation.
- **Watch History:** View Plex watch activity with filtering by user, show, media type, and date range.
- **User List:** Admins can view Plex users, last login times, and latest watched items.
- **Episode Detail Pages:** Individual episode pages now show air date and an "Available" label when the file exists.
- **Episode Lists:** Season 0 is hidden from show pages and episodes indicate availability instead of download status.
- **Notification & Reporting System:** Added database tables for user show preferences, notifications, and issue reports with a simple admin review page.

---
### 🚀 Latest Enhancements
- **UI/UX Consistency:**
    - Standardized header appearance between the main application and the admin panel. The admin panel header is now full-width for better space utilization.
    - Improved main site search bar responsiveness on mobile devices, featuring a modal display for results.
- **Image Handling:**
    - Ensured all primary content images (posters, backdrops) consistently use locally cached static paths (e.g., `/static/poster/[id].jpg`).
    - Implemented robust image fallbacks using `onerror` attributes, pointing to generic placeholder images for missing posters or backdrops.
- **Content Discovery & Navigation:**
    - **Show Detail Page:**
        - Confirmed Season 0 ("Specials") is hidden from episode lists.
        - Added a "Recently/Currently Watched" card to highlight the user's latest interacted episode, including progress and a direct link.
        - Episodes are clearly marked as "Available" if the media file exists.
    - **Episode Detail Page:**
        - Revamped to display comprehensive information: show's poster, episode title, season/episode number, formatted air date, availability status, overview, runtime, and rating (when available).
        - Includes a "Back to Show" link for easy navigation.
- **Admin Panel:**
    - **Unified Search:** Introduced a new search bar in the admin header, allowing administrators to search across Shows, Movies (linking to main site details), and Admin panel routes (e.g., Dashboard, Settings).
---

### Admin Panel & Service Management
- **Dynamic Service Status:** The admin services page (`/admin/settings`) now features real-time status indicators.
  - On page load, dots are colored green or red based on an initial connection test.
  - Clicking the "Test" button for any service triggers a live API check and updates the dot color instantly without a page reload.
- **New Admin Panel UI:** Introduced a dedicated admin section (`/admin/dashboard`) with a responsive sidebar and a new dashboard page. The service configuration page is now part of this new layout.
- **Admin Tasks Page & Sync Enhancements:** Introduced a dedicated Admin Tasks page (`/admin/tasks`) for Sonarr and Radarr library synchronization. This includes:
    - Clearer separation of sync actions.
    - User feedback via flash messages indicating the number of shows/movies processed.
    - Consistent UI styling for sidebar links (e.g., 'Tasks' link) and action buttons.
    - Corrected logo display for Sonarr/Radarr in both light and dark modes on the tasks page.
- **Plex Integration:** Resolved Plex OAuth login/logout flows, session management. Enhanced Plex webhook handling to capture detailed events (play, pause, resume, stop, scrobble) into a new `plex_activity_log` table. The homepage now displays "Now Playing" or "Recently Played" information for the logged-in user based on this detailed log.
- **Search Image Handling:** Fixed display of Sonarr/Radarr images in search results by ensuring absolute URLs are used and API keys are included for image fetching and caching.

### UI & Styling
- **Tailwind CSS & Dark Mode:** The entire application uses Tailwind CSS for styling, including full dark mode support.
- **Dynamic Logos:** All service logos on the admin page support both light and dark modes with automatic switching.
- **API Key Links:** Links for Sonarr, Radarr, and Bazarr now point directly to the relevant settings page within those applications.

### Static Asset Serving
- Static files are served from `/app/static` using Flask’s best practices.
- All static asset references use `url_for('static', filename=...)`.

### Development Setup
- **Requirements:** Python 3.x, Node.js (v18+), npm (v9+)
- **Tailwind Build:**
  ```bash
  npx tailwindcss -i ./app/static/input.css -o ./app/static/css/style.css --watch
  ```
- **Run the app:**
  ```bash
  python3 run.py
  ```
- **Automated Development Server (with Watchdog & Tailwind)**

For a more robust development setup that includes automatic Flask server restarts on Python file changes and simultaneous Tailwind CSS watching, an advanced configuration using `systemd`, `tmux`, and `watchmedo` is available.

This setup provides:
- Automatic restart of the Flask development server when `.py` files are modified.
- Continuous Tailwind CSS compilation in watch mode.
- Both processes managed by a single `systemd` service for easy start/stop/monitoring.

**For detailed setup instructions, please refer to: [`docs/dev-server-watchdog.md`](docs/dev-server-watchdog.md)**

Once configured, you can monitor the live output of both Flask and Tailwind using:
```bash
tmux attach -t shownotes
```

---

## Features

### Core Functionality
- **Spoiler-Aware Character Summaries:** Obtain character summaries conscious of viewing progress, including bio, quotes, and significant relationships. Generated using Ollama with prompt templates, limited by season/episode.
- **Relationship Mapping and Actor Overlap:** Compare shows/movies to find overlapping actors, highlighting shared cast members and their roles.
- **Interactive Character Chat:** Engage in chat-style Q&A with fictional characters, role-played by LLM.
- **Integration with TV Metadata Services:** Interfaces with Sonarr and Radarr for show and movie information, cast lists, images, and descriptions. Connects with Sonarr and Radarr for upcoming episode and movie schedules and Plex for tracking viewed episodes. Import subtitles from Bazarr to store in the database to provide the LLM with insite and allow the user to search for dialogue in episodes. 
- **Spoiler Tracking and Summaries:** Limits summaries to specific episodes based on Plex data or user input, maintaining a watch log and "currently watching" record in SQLite.
- **Autocomplete:** Show and character fields use `/autocomplete/shows` and `/autocomplete/characters` endpoints.
- **Character Summary Page:** Form posts to `/character-summary`, displays TMDB image, and renders summary with personality traits, key events, relationships, importance, and quote.
- **Actor & Character Search:**
    - `search()`: Finds show/movie by name using api to pull from radarr and sonarr since all shows in Plex are in these databases
    - `find_actor_by_name()`: Finds actor by character name in a show.
    - `get_cast()`: Retrieves cast list and episode info.
- **Character Summary System:**
    - `summarize_character()`: Generates and parses structured character summary.
    - `get_character_summary()`: Prompts GPT for structured sections.
    - `parse_character_summary()`: Extracts and cleans structured data.
    - SQLite caching for summaries: `save_character_summary_to_db()`, `get_cached_summary()`.
- **Actor Insights:**
    - `get_actor_details()`: Builds enriched profile with known-for roles and links.
    - `get_known_for()`: Most popular appearances.
- **In-Character AI Chat:**
    - `chat_as_character()`: Roleplays as a character using local LLM.
- **Metadata Management:**
    - `save_show_metadata()` / `get_show_metadata()`
    - `save_season_metadata()` / `get_season_metadata()`
    - `get_show_backdrop()`: Gets show image for headers.
    - `get_reference_links()`: Wikipedia, Fandom, IMDb, TMDB links.
- **Character Ranking:**
    - `save_top_characters()` / `get_top_characters()`: Track main characters by episode count.
- Auto-refresh calendar with Sonarr API.
- Plex webhook support to adjust spoiler level automatically (partially implemented, needs refinement).
- UI Enhancements: Dark mode toggle, mobile chat enhancements.
- User authentication using plex authentication or user/password imported from plex (like Jellyseerr) & personal watch history.

- Admin onboarding with fields for Radarr, Sonarr, Bazarr and Ollama configuration. Includes dynamic API connection tests and Plex authentication. (Initial service settings page available, full admin dashboard and expanded configuration is on the roadmap).
- Users can report file issues with a movie or episode to the adminstator that sends notificaitions to the backend and to https://pushover.net


## Architecture/Tech Stack

### Backend
- Python 3, Flask

### Database
- SQLite3 (`data/shownotes.db` or `db.sqlite3`)

### Frontend
- HTML, CSS, JavaScript
- Jinja2 for templating

### Key Files & Modules
- **`app/__init__.py`**: Flask app factory (`create_app()`). Initializes the Flask app, registers the main application blueprint, and configures Jinja filters.
- **`app/routes/main.py`**: Contains user-facing routes (e.g., homepage, character summaries) using the `main_bp` blueprint.
- **`app/routes/admin.py`**: Contains admin-specific routes (e.g., settings, tasks, logs) under the `/admin` prefix, using the `admin_bp` blueprint.
- **`app/utils.py`**: All major logic, including TMDB calls, OpenAI calls, summary generation, database operations, and parsing functions.
- **`app/prompts.py` / `app/prompt_builder.py`**: Prompt templates for OpenAI queries. Defines reusable prompt templates for tasks like character summaries, quotes, and relationship lists.
- **`app/templates/`**: Jinja2 HTML templates.
- **`app/static/`**: CSS, JS, images. Includes `autocomplete.js` for dynamic suggestion dropdowns.
- **`logs/`**: Parsed receipt logs and app logs.
- **`admin/`**: Admin tools, stats, API cost views.
- **`run.py`**: Main Flask launcher.
- **`shownotes.service`**: systemd service unit file.
- **`requirements.txt`**: Python dependencies.

### File Structure Overview
```
shownotes/
├── app/
│   ├── __init__.py            # Flask app factory
│   ├── routes/                # Blueprint-based route definitions
│   │   ├── admin.py           # Admin panel routes (/admin/*)
│   │   └── main.py            # Main application routes
│   ├── utils.py               # Helper functions
│   ├── prompts.py             # Prompt templates for OpenAI queries
│   ├── templates/             # Jinja2 HTML templates
│   └── static/                # CSS, JS, images
├── logs/                      # Parsed receipt logs and app logs (Note: some docs show data/ for db)
├── backend/                   # Admin tools, stats, API cost views
├── db.sqlite3                 # SQLite3 database (Note: some docs show data/shownotes.db)
├── run.py                     # Main Flask launcher
├── shownotes.service          # systemd service unit file
├── requirements.txt           # Python dependencies
└── README.md
```

## API Integration

### TMDB API
- Used for metadata and casting.
- Fetches show information, cast lists, images (posters/backdrops), and descriptions.
- Key functions: `search_tmdb()`, `get_cast()`, `get_known_for()`, `get_show_backdrop()`.

### Ollama API
- Used for character summaries and in-character replies (GPT-4).
- Generates structured character summaries and enables chat functionality.
- Key functions: `get_character_summary()`, `chat_as_character()`.
- All API calls are tracked in the SQLite database (`api_usage` table) for cost monitoring.
- Prompts are built using templates from `app/prompts.py` or `app/prompt_builder.py`.

- Integration via webhooks to track viewed episodes.
- The `/plex-webhook` route handles incoming POST requests when an episode is watched.
- Updates `current_watch` table and `webhook_log` table.
- This data can be used to adjust spoiler levels for summaries.
- **Plex OAuth login** using PIN-based flow. Credentials are securely stored in the database, not in .env files.
- **Webhook event display:** Homepage shows the most recent relevant activity (play, pause, resume, stop, scrobble) for the logged-in user, sourced from the `plex_activity_log` table, including rich metadata and poster image.

### Sonarr
- Used to retrieve upcoming episode schedules for a calendar view.
- Use the show metadata import into Shownotes
- The `/calendar/full` endpoint is intended to serve this data.
- `fetch_sonarr_calendar()` function in `app/sonarr_calendar.py`.

### Radarr
- Use Radarr API to import movie metadata into Shownotes and display upcoming movie releases

### Bazarr
- Use Bazarr API to insert subtitles to the Shownotes DB for the user to search and the LLM to add context.

## Database

The application uses an SQLite database (typically `data/shownotes.db` or `db.sqlite3`). No ORM is used; queries are generally raw SQL.

### Key Tables

-   **`character_summaries`**: Caches generated character summaries.
    *   `id` (INTEGER PRIMARY KEY)
    *   `character_name` (TEXT)
    *   `show_title` (TEXT)
    *   `season_limit` (INTEGER)
    *   `episode_limit` (INTEGER)
    *   `raw_summary` (TEXT)
    *   `parsed_traits` (TEXT)
    *   `parsed_events` (TEXT)
    *   `parsed_relationships` (TEXT)
    *   `parsed_importance` (TEXT)
    *   `parsed_quote` (TEXT)
    *   `timestamp` (DATETIME DEFAULT CURRENT_TIMESTAMP)
-   **`character_chats`**: Logs chat interactions with characters.
    *   `id` (INTEGER PRIMARY KEY)
    *   `character_name` (TEXT)
    *   `show_title` (TEXT)
    *   `user_message` (TEXT)
    *   `character_reply` (TEXT)
    *   `timestamp` (DATETIME DEFAULT CURRENT_TIMESTAMP)
-   **`api_usage`**: Logs each OpenAI API call.
    *   `id` (INTEGER PRIMARY KEY)
    *   `timestamp` (DATETIME)
    *   `endpoint` (TEXT) (e.g., `gpt-4`)
    *   `prompt_tokens` (INTEGER)
    *   `completion_tokens` (INTEGER)
    *   `total_tokens` (INTEGER)
    *   `cost_usd` (REAL)
-   **`shows` / `show_metadata`**: Stores high-level information about shows (title, TMDB ID, description, poster/backdrop paths).
-   **`season_metadata`**: Stores information on seasons of shows.
-   **`top_characters`**: Stores main characters for each show (character name, actor, episode count).
-   **`current_watch`**: Tracks the latest episode watched per user (from Plex webhooks).
-   **`webhook_log`**: Records a minimal log of every Plex webhook event received (older table).
-   **`plex_activity_log`**: Stores detailed information for various Plex webhook events (e.g., `media.play`, `media.pause`, `media.resume`, `media.stop`, `media.scrobble`), including `event_type`, `plex_username`, `media_type`, `title`, `show_title`, `season_episode`, `player_uuid`, `session_key`, `view_offset_ms`, `duration_ms`, `event_timestamp`, and `raw_payload`.
-   **`autocomplete_logs`**: Records when a user selects an autocomplete suggestion.
-   **`plex_events`**: Older table for basic Plex play events (largely superseded by `plex_activity_log` for detailed tracking but kept for some historical context or specific uses).

### Database Initialization
Tables are created automatically the first time you run the database initialization command.
Run the following to create a fresh SQLite database:

```bash
FLASK_APP=shownotes.run flask init-db
```

This command sets up all tables defined in `app/database.py`.

## Installation & Setup

1. **Install Python dependencies**
   ```bash
   pip install flask requests
   ```

2. **Initialize the SQLite database**
   ```bash
   FLASK_APP=shownotes.run flask init-db
   ```

3. **Run the development server**
   ```bash
   python -m shownotes.run
   ```

## Development Guide

### Developer Notes
-   Modular logic for summaries, relationship formatting, and OpenAI calls lives in `app/utils.py`.
-   Character and show summaries can be cached in the database to reduce API calls (see Database section).
-   Admin tools are available at `/admin` .
-   `shownotes.service` (for systemd) restarts the app automatically if it crashes.
-   Run `FLASK_APP=shownotes.run flask init-db` to create the database schema.

### Prompt Templates
-   Prompt templates are structured in `app/prompts.py` or `app/prompt_builder.py`.
-   Example structure:
    ```python
    SUMMARY_PROMPT_TEMPLATE = """
    Provide a character summary for {character} from {show}, up to Season {season}, Episode {episode}.
    Include:
    - A short character bio
    - A quote that captures their personality
    - A section titled “Significant Relationships” formatted as a bulleted list. Each bullet should name the person, identify their role, and include a short description.
    """
    ```
-   Prompts can be easily adjusted to include other attributes like motivations, key arcs, or symbolic moments.

### OpenAI or Ollama API Usage & Cost Tracking
-   All API calls to OpenAI are tracked in the SQLite database table: `api_usage`.
-   Columns include: `id`, `timestamp`, `endpoint`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost_usd`.
-   A dashboard is under development at `/admin/usage` (or `/admin/api-usage`) to view and export cost breakdowns.
-   Use `utils.log_openai_usage()` (or similar, function name might vary) to log calls programmatically.
-   To keep costs low, batch prompts when possible and cache results for repeated queries.
