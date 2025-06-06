# show_notes
Your plex television companion
# ShowNotes

## Overview

ShowNotes is a Flask-based web app that helps users explore TV shows, character arcs, and actor overlap between series. It offers spoiler-aware summaries, relationship mapping, chat-style interaction, and integration with metadata sources like local installations of Radarr, Sonarr, Bazarr, Tautulli and Ollama.

The purpose of ShowNotes is to be a tool for exploring tv show, season and character summaries, overlap detection, actor insights, and spoiler-aware recaps based on viewing progress. Using a plex webhook the plex users' viewing is imported and stored in a sqlite3 database for each user. Using Jellyseer as inspiration for layout and visual deesign to be usable on a phone and computer. Also use plex autentication to sign in for an administrator and users. 

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
- Visualize character relationships and timelines.
- Add actor overlap Venn diagrams.
- Create spoiler-free recaps (distinct from character summaries).
- Optimize caching and reduce LLM calls by storing all queries in the db
- Support multiple spoiler versions of summaries.
- Autocomplete keyboard navigation in the search bar 
- Style character summary card to match rest of app (mobile-first polish).
- Standardize layout across all forms and cards for consistency.
- Create reusable template block for summary + chat output formatting.
- Add error messages or fallbacks when summary generation fails.
- Integrate Sonarr calendar with episode hover previews and filters (premieres, finales, etc.).
- Admin Dashboard: Recent LLM queries, API usage summary , JSON route links for IOS Shortcuts, Logs of uploaded or parsed data.
- Admin Dashboard: view and edit the LLM prompts
- Admin Dashboard: settings for Radarr, Sonarr, Bazarr, Ollama urls and API keys (https://sonarr.tv/docs/api/, https://radarr.video/docs/api/
 - Admin onboarding with fields for Radarr, Sonarr, Bazarr and Ollama configuration. Includes dynamic API connection tests and Plex authentication.
- Users can report file issues with a movie or episode to the adminstator that sends notificaitions to the backend and to https://pushover.net
- Finalize reusable prompt templates (summary, relationships, arcs, quotes).
- Add prompt-based regeneration with spoiler limits (e.g., “up to Season 2”).
- Add ability to regenerate summaries with new context or version tags.
- Display poster/banner in “Currently Watching” section.
- Show calendar with upcoming Sonarr episodes (not completed).
- Add modals for character previews when clicked from list.
- Use chat UI libraries to create a messenger-style interface.
- Add character chat mode: “Chat with [Character]” using limited context (basic version present, needs expansion).
- Add chat UI for general Q&A about a show, character, or episode with a tv show critic or expert

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
- **`app/routes.py`**: All route definitions. Handles page requests and API endpoints, including user-facing pages, autocomplete APIs, integration webhooks, and admin/utility routes.
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
│   ├── routes.py              # All route definitions
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

### Plex
- Integration via webhooks to track viewed episodes.
- The `/plex-webhook` route handles incoming POST requests when an episode is watched.
- Updates `current_watch` table and `webhook_log` table.
- This data can be used to adjust spoiler levels for summaries.

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
-   **`webhook_log`**: Records every Plex webhook event received.
-   **`autocomplete_logs`**: Records when a user selects an autocomplete suggestion.

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

