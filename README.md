# ShowNotes

Your Plex television companion.

ShowNotes is a self-hosted web application that helps you explore your TV show and movie library with rich metadata, viewing history tracking, AI-powered summaries, and deep integration with popular media management tools. Inspired by the design of Jellyseerr, it works great on both desktop and mobile.

<!-- Screenshot: Homepage showing currently watching, recently watched, and personalized recommendations -->
![Homepage](docs/screenshots/homepage.png)

---

## Features

### Personalized Homepage
A dashboard tailored to each user showing currently watching, recently played, and personalized content based on viewing history.

<!-- Screenshot: Homepage with currently playing card and recently watched grid -->

### Show & Movie Detail Pages
Detailed pages for every show and movie in your library with background art, metadata, season/episode breakdowns, and your current watch progress.

<!-- Screenshot: Show detail page with background image, metadata, and collapsible seasons -->

### TV Calendar
Browse upcoming episodes from your library in a calendar view, so you always know what's airing next.

<!-- Screenshot: Calendar view showing upcoming episodes -->

### AI-Powered Summaries
Generate show and season summaries using Ollama or OpenAI. Summaries are generated on a configurable schedule and displayed on show detail pages.

<!-- Screenshot: Show detail page with AI-generated season summary -->

### Universal Search
Search across your entire TV and movie library from the header. On mobile, search expands to a full overlay for easy use.

<!-- Screenshot: Search results dropdown showing shows and movies -->

### Actor & Character Pages
Explore character details and discover actor overlap between shows in your library — find out which actors appear across multiple series.

<!-- Screenshot: Character detail page showing actor info and cross-show appearances -->

### User Profiles
Each user gets a profile with favorites, watch history, statistics, progress tracking, custom lists, and notification preferences.

<!-- Screenshot: Profile page showing statistics and watch history -->

### Dark Mode
Full light and dark mode support throughout the entire application, toggled from the header.

<!-- Screenshot: Side-by-side light and dark mode comparison -->

### Responsive Design
Fully responsive layout that works on phones, tablets, and desktops. The header adapts with a two-row layout on mobile for comfortable use.

<!-- Screenshot: Mobile view showing responsive header and layout -->

### Admin Dashboard
A comprehensive admin panel for managing services, running sync tasks, viewing logs, managing users, and configuring the application.

<!-- Screenshot: Admin dashboard overview -->

### Service Configuration & Onboarding
First-run onboarding wizard and admin settings page with real-time connection testing for all integrated services.

<!-- Screenshot: Admin settings page showing service cards with status indicators -->

### Background Scheduler
Automated sync tasks run on a configurable schedule — Tautulli watch history, Sonarr/Radarr library syncs, and AI summary generation all happen in the background.

### Webhook Integration
Receives webhooks from Plex, Sonarr, and Radarr to keep your library and watch history in sync automatically without manual intervention.

### Issue Reporting
Users can report file issues (missing episodes, bad quality) directly from the app. Admins receive notifications via Pushover.

---

## Integrations

| Service | Purpose |
|---------|---------|
| **Plex** | OAuth authentication, viewing history via webhooks (play/pause/resume/stop/scrobble) |
| **Sonarr** | TV show library, episode metadata, webhooks for automatic syncing |
| **Radarr** | Movie library, metadata, webhooks for automatic syncing |
| **Tautulli** | Watch history synchronization |
| **Bazarr** | Subtitle import for search |
| **Ollama** | Local LLM for AI-powered show/season summaries |
| **OpenAI** | Cloud LLM alternative for AI summaries |
| **Pushover** | Admin notifications for issue reports |
| **TheTVDB** | Additional metadata enrichment |

---

## Tech Stack

- **Backend:** Python 3 / Flask
- **Database:** SQLite3 (no ORM — direct queries)
- **Frontend:** Tailwind CSS, Alpine.js, Jinja2 templates
- **Task Scheduling:** APScheduler
- **Production Server:** Gunicorn
- **Deployment:** Docker / Docker Compose

---

## Installation

### Docker (Recommended)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/scottwf/show_notes.git
   cd show_notes
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your settings (service URLs, API keys, etc.)
   ```

3. **Deploy:**
   ```bash
   ./deploy.sh
   ```

   The deploy script handles directory creation, file syncing, database migrations, and container management automatically.

4. **Access ShowNotes** at `http://your-server:5003`

### Manual / Development

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   npm install
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

3. **Run the development server:**
   ```bash
   python3 run.py
   ```

4. **Watch Tailwind CSS** (in a separate terminal, for UI development):
   ```bash
   ./watch_tailwind.sh
   ```

The database is created automatically on first run. Default port is **5003**.

---

## Configuration

All service configuration is managed through the admin settings page (`/admin/settings`) after first-run onboarding. Settings are stored in the database, not in environment files.

Environment variables in `.env` are used to pre-populate the onboarding form and configure Flask internals:

| Variable | Description |
|----------|-------------|
| `ENVIRONMENT` | `development` or `production` |
| `SECRET_KEY` | Flask session secret (change in production) |
| `SONARR_URL` / `SONARR_API_KEY` | Sonarr connection |
| `RADARR_URL` / `RADARR_API_KEY` | Radarr connection |
| `TAUTULLI_URL` / `TAUTULLI_API_KEY` | Tautulli connection |
| `BAZARR_URL` / `BAZARR_API_KEY` | Bazarr connection |
| `OLLAMA_URL` / `OLLAMA_MODEL` | Ollama LLM connection |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | OpenAI LLM connection |
| `PUSHOVER_USER_KEY` / `PUSHOVER_API_TOKEN` | Push notifications |

---

## Project Structure

```
show_notes/
├── app/
│   ├── __init__.py              # Flask app factory
│   ├── database.py              # Database connection, schema, migrations
│   ├── utils.py                 # Service integrations, sync logic, image handling
│   ├── summary_services.py      # AI/LLM summary generation
│   ├── episode_data_services.py # Episode-specific data management
│   ├── scheduler.py             # APScheduler background task configuration
│   ├── cli.py                   # Flask CLI commands
│   ├── routes/
│   │   ├── main.py              # User-facing routes
│   │   └── admin.py             # Admin panel routes (/admin/*)
│   ├── templates/               # Jinja2 HTML templates
│   ├── static/                  # CSS, JS, images, logos
│   └── migrations/              # Database migration scripts
├── docker-compose.yml
├── Dockerfile
├── deploy.sh                    # Docker deployment script
├── run.py                       # Flask application launcher
├── requirements.txt             # Python dependencies
├── tailwind.config.js           # Tailwind CSS configuration
└── .env.example                 # Environment variable template
```

---

## Roadmap

Planned features and improvements:

- **Spoiler-Aware Summaries** — AI summaries that respect each user's viewing progress, so you never get spoiled beyond what you've watched
- **Character Chat** — Chat-style Q&A with fictional characters, role-played by your local or cloud LLM
- **Relationship Mapping** — Visual relationship maps between characters within a show
- **Subtitle Search** — Search dialogue across episodes using imported Bazarr subtitles
- **Jellyseerr Integration** — Request new shows and movies directly from ShowNotes
- **Multi-User Recommendations** — Suggest shows based on overlapping tastes between household members
- **Watch Party Sync** — Coordinate viewing sessions with other users in your Plex server
- **Mobile App / PWA** — Progressive web app support for a native-like mobile experience
- **Trakt.tv Integration** — Sync watch history and ratings with Trakt
- **Custom Lists & Collections** — Curated lists that can be shared between users

---

## License

This project is for personal use.
