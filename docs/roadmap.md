# Project Roadmap

This document outlines the planned features and development stages for the ShowNotes application.

## Completed
- [x] Plex OAuth login (PIN-based, DB-stored credentials)
- [x] Show most recent Plex event for logged-in user on homepage
- [x] Integrate Sonarr/Radarr APIs for reliable poster/metadata display
- [x] Admin settings UI for service URLs and API keys
- [x] Basic Flask application structure
- [x] Database setup (SQLite)
- [x] Tailwind CSS integration
- [x] Basic HTML templates and routes
- [x] Initial documentation setup

## Next Steps
- [ ] Improve robustness of Plex user detection at login (handle edge cases, more reliable username/id capture)
- [ ] Add caching or proxying for poster images to improve performance and reliability
- [ ] Consider showing a history/list of recent events per user
- [ ] Add more metadata from Sonarr/Radarr to homepage card
- [ ] UX: Add loading/error states for poster fetches
- [ ] Document setup and troubleshooting for multi-user environments

## Phase 2: Core Functionality
- [ ] Spoiler-aware character summaries (Ollama integration)
- [ ] Relationship mapping and actor overlap
- [ ] "Currently Watching" tracking (Plex webhook integration)
- [ ] Admin panel for API key configuration

## Phase 3: Advanced Features & UI Polish
- [ ] Interactive character chat (Ollama)
- [ ] Advanced search and filtering
- [ ] Subtitle integration (Bazarr)
- [ ] Mobile-first UI refinement
- [ ] Comprehensive testing

## Future Ideas
- [ ] User-specific watch history and recommendations
- [ ] Customizable dashboards
- [ ] Notification system (Pushover integration for file issues)
