# Project Roadmap

This document outlines the planned features and development stages for the ShowNotes application.

## Completed
- [x] **Dynamic Service Status Indicators:** Added visual connection status indicators (green/red dots) for configured services that update in real-time via JavaScript.
- [x] Plex OAuth login (PIN-based, DB-stored credentials), logout, session management, and onboarding fixes.
- [x] Show most recent Plex event for logged-in user on homepage (Plex Webhook processing fixes and schema updates).
- [x] Integrate Sonarr/Radarr APIs for reliable poster/metadata display.
- [x] Admin settings UI for service URLs and API keys (initial version).
- [x] Separated Sonarr and Radarr library sync functionalities with dedicated admin actions.
- [x] Foundational Admin Panel UI: Responsive sidebar, dashboard page (`/admin/dashboard`), and integration of service settings into the new layout.
- [x] Basic Flask application structure.
- [x] Database setup (SQLite).
- [x] Tailwind CSS integration & Dark Mode.
- [x] Basic HTML templates and routes.
- [x] Initial documentation setup.

## Next Steps
- [ ] Add caching or proxying for poster images to improve performance and reliability
- [ ] Improve robustness of Plex user detection at login (handle edge cases, more reliable username/id capture)
- [ ] Consider showing a history/list of recent events per user
- [ ] Add more metadata from Sonarr/Radarr to homepage card
- [ ] UX: Add loading/error states for poster fetches
- [ ] Document setup and troubleshooting for multi-user environments

## Phase 2: Core Functionality
- [ ] Spoiler-aware character summaries (Ollama integration)
- [ ] Relationship mapping and actor overlap
- [ ] "Currently Watching" tracking (Plex webhook integration)


## Admin Panel Development (Phase 2)
- [ ] **Dashboard Enhancements:**
    - [ ] Display real-time usage statistics (e.g., active users, Plex events processed).
    - [ ] Show recent user logins.
    - [ ] Implement a notification system for important alerts or errors.
- [ ] **Services Page Enhancements:**
    - [ ] Allow full configuration of service URLs, ports, and API keys directly from this page (expanding current capabilities).
- [ ] **Database Management Page:**
    - [ ] Provide UI controls for manual library synchronization (Sonarr, Radarr, potentially others like Bazarr later).
    - [ ] Display statistics from the local database (e.g., number of shows, movies, episodes, users).
- [ ] **LLM Model Prompts Management Page:**
    - [ ] Allow viewing and editing of LLM prompt templates used by the application.
    - [ ] Display usage statistics for different prompts.
- [ ] **User Management Page:**
    - [ ] Display a list of registered users and their details.
    - [ ] (Future) Add ability to manage user roles or permissions.
- [ ] **Help & Documentation Page:**
    - [ ] Provide in-app documentation for administrators and users.
    - [ ] Include troubleshooting tips and guides.

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
